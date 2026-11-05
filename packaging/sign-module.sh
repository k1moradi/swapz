#!/usr/bin/env bash
# Sign qualification modules at build time; packaging uses --verify only.
set -Eeuo pipefail

blocked() {
    printf 'BLOCKED: Secure Boot module signing: %s\n' "$*" >&2
    exit 2
}

blocked_phase() {
    local phase="$1" command_status="$2"
    local expected_state=qualified_module_identity observed_state=unverified
    local next_action=inspect_signing_evidence_read_only
    shift 2
    case "$phase" in
        certificate_enrollment)
            expected_state=configured_certificate_enrolled
            observed_state=enrollment_unverified
            next_action=inspect_public_mok_enrollment_read_only ;;
        certificate_material)
            expected_state=readable_configured_public_certificate
            observed_state=certificate_unavailable
            next_action=inspect_public_certificate_permissions_read_only ;;
        detached_signature)
            expected_state=valid_signature_from_enrolled_certificate
            observed_state=unsigned_malformed_or_unverified
            next_action=inspect_qualified_module_signature_read_only ;;
        signature_generation)
            expected_state=valid_build_time_module_signature
            observed_state=signing_failed
            next_action=inspect_signing_tool_status_without_key_material ;;
    esac
    # Never replay signer output, private key/certificate paths or material,
    # and never claim that the running kernel accepted the signed module.
    printf 'BLOCKED: Secure Boot module signing: %s; artifact=dm-swapz.ko phase=%s expected=%s observed=%s command_status=%s next=%s kernel_acceptance=unproven\n' \
        "$*" "$phase" "$expected_state" "$observed_state" "$command_status" "$next_action" >&2
    exit 2
}

mode=sign
if [[ $# == 2 && $1 == --verify ]]; then
    mode=verify
    module="$2"
elif [[ $# == 1 ]]; then
    module="$1"
else
    blocked "internal helper requires MODULE or --verify MODULE"
fi

helper_path="${BASH_SOURCE[0]}"
case "$helper_path" in
    */*) helper_dir="${helper_path%/*}" ;;
    *) helper_dir=. ;;
esac
project_root="$(CDPATH= cd -- "$helper_dir/.." && pwd -P)"

sign_test_root="${SWAPZ_SIGN_TEST_ROOT:-}"
if [[ -n "$sign_test_root" ]]; then
    [[ $(id -u) != 0 ]] || blocked "root test mode forbidden"
    sign_test_root="$(realpath -m -- "$sign_test_root")"
    case "$sign_test_root" in "$project_root/build/tests/"*) ;; *)
        blocked "test signing sandbox is outside build/tests" ;;
    esac
    module_real="$(realpath -m -- "$module")"
    case "$module_real" in "$sign_test_root"/*) ;; *)
        blocked "test module is outside the signing sandbox" ;;
    esac
else
    PATH=/usr/sbin:/usr/bin:/sbin:/bin
    export PATH
fi

[[ -f "$module" && ! -L "$module" ]] ||
    blocked_phase module_presence 1 "built dm-swapz.ko is missing or not a regular file"

secure_boot_state() {
    local output value
    local -a variables

    if command -v mokutil >/dev/null 2>&1; then
        output="$(LC_ALL=C mokutil --sb-state 2>/dev/null || true)"
        case "$output" in
            *"SecureBoot enabled"*) printf '%s\n' enabled; return ;;
            *"SecureBoot disabled"*) printf '%s\n' disabled; return ;;
        esac
    fi

    if [[ ! -d /sys/firmware/efi ]]; then
        printf '%s\n' disabled
        return
    fi

    shopt -s nullglob
    variables=(/sys/firmware/efi/efivars/SecureBoot-*)
    shopt -u nullglob
    if (( ${#variables[@]} == 1 )) && [[ -r ${variables[0]} ]] &&
       command -v od >/dev/null 2>&1; then
        value="$(od -An -t u1 -j 4 -N 1 "${variables[0]}" 2>/dev/null |
                 tr -d '[:space:]')"
        case "$value" in
            1) printf '%s\n' enabled; return ;;
            0) printf '%s\n' disabled; return ;;
        esac
    fi

    printf '%s\n' unknown
}

state="$(secure_boot_state)"
[[ "$state" != disabled ]] || exit 0
[[ "$state" == enabled ]] ||
    blocked_phase secure_boot_state 1 "cannot determine EFI Secure Boot state"

key="${SWAPZ_MOK_PRIVATE_KEY:-/var/lib/shim-signed/mok/MOK.priv}"
cert="${SWAPZ_MOK_CERT:-/var/lib/shim-signed/mok/MOK.der}"

command -v openssl >/dev/null 2>&1 ||
    blocked_phase detached_signature 127 "openssl is required"
command -v python3 >/dev/null 2>&1 ||
    blocked_phase detached_signature 127 "python3 is required"
command -v mktemp >/dev/null 2>&1 ||
    blocked_phase detached_signature 127 "mktemp is required"
if [[ "$mode" == sign ]]; then
    command -v kmodsign >/dev/null 2>&1 ||
        blocked_phase signature_generation 127 "kmodsign is required"
fi

sudo_command=()
need_sudo() {
    if (( ${#sudo_command[@]} == 0 )); then
        command -v sudo >/dev/null 2>&1 ||
            blocked "sudo is required to read protected MOK material"
        sudo_command=(sudo)
        if [[ ${SWAPZ_SIGN_NONINTERACTIVE:-0} == 1 ]]; then
            sudo_command+=(-n)
        fi
    fi
}

cert_requires_sudo=0
if [[ -r "$cert" ]]; then
    [[ -f "$cert" && ! -L "$cert" ]] ||
        blocked "MOK certificate is not a regular file"
else
    if [[ "$mode" == verify ]]; then
        blocked_phase certificate_material 1 \
            "MOK certificate is unavailable for signature verification"
    fi
    need_sudo
    "${sudo_command[@]}" test -f "$cert" &&
        "${sudo_command[@]}" test ! -L "$cert" ||
        blocked "MOK certificate is missing, unsafe, or sudo authorization is unavailable"
    cert_requires_sudo=1
fi

command -v mokutil >/dev/null 2>&1 ||
    blocked_phase certificate_enrollment 127 \
        "mokutil is required to verify MOK enrollment"

mokutil_enrollment_status=0
mokutil_reports_enrolled() {
    local output status

    # Query the firmware MOK list directly. The kernel-keyring probe is a
    # separate runtime fact and can fail for an unprivileged build process.
    if (( cert_requires_sudo == 1 )); then
        if output=$("${sudo_command[@]}" env LC_ALL=C mokutil \
                --ignore-keyring --test-key "$cert" 2>&1); then
            status=0
        else
            status=$?
        fi
    else
        if output=$(env LC_ALL=C mokutil --ignore-keyring --test-key \
                "$cert" 2>&1); then
            status=0
        else
            status=$?
        fi
    fi

    mokutil_enrollment_status="$status"

    # mokutil 0.7.2 returns 1 when the key is already enrolled and prints this
    # exact path-bound message. Its status 0 says "not enrolled"; silence or
    # any other status/output is not enrollment evidence.
    if (( status == 1 )) &&
       [[ "$output" == "$cert is already enrolled" ]]; then
        return 0
    fi
    return 1
}

if ! mokutil_reports_enrolled; then
    blocked_phase certificate_enrollment "$mokutil_enrollment_status" \
        "configured MOK certificate is not enrolled or enrollment could not be verified"
fi

restore_build_module_owner() {
    [[ "$mode" == sign ]] || return 0
    (( EUID != 0 )) || return 0
    command -v stat >/dev/null 2>&1 ||
        blocked "stat is required to preserve build-module ownership"

    local current_owner expected_owner
    current_owner="$(stat -c '%u:%g' -- "$module")" ||
        blocked "cannot inspect build-module ownership after signing"
    [[ "$current_owner" =~ ^[0-9]+:[0-9]+$ ]] ||
        blocked "build-module ownership result is malformed"
    expected_owner="$(id -u):$(id -g)" ||
        blocked "cannot determine build user ownership"
    [[ "$current_owner" == "$expected_owner" ]] && return 0

    # sudo kmodsign can replace the output inode with a root-owned file. The
    # surrounding Makefile must be able to set the final mode and rebuild it.
    need_sudo
    "${sudo_command[@]}" chown -- "$expected_owner" "$module" ||
        blocked "cannot restore build-module ownership after signing"
    current_owner="$(stat -c '%u:%g' -- "$module")" ||
        blocked "cannot verify build-module ownership after signing"
    [[ "$current_owner" == "$expected_owner" ]] ||
        blocked "build-module ownership was not restored after signing"
}

extract_module_signature() {
    local payload_path="$1" signature_path="$2"
    python3 - "$module" "$payload_path" "$signature_path" <<'PY'
import sys
from pathlib import Path

marker = b"~Module signature appended~\n"
header_size = 12
module = Path(sys.argv[1]).read_bytes()
if not module.endswith(marker):
    raise SystemExit(10)
header_offset = len(module) - len(marker) - header_size
if header_offset < 0:
    raise SystemExit(11)
header = module[header_offset:header_offset + header_size]
if len(header) != header_size:
    raise SystemExit(11)
algorithm = header[0]
hash_identifier = header[1]
signature_type = header[2]
signer_length = header[3]
key_id_length = header[4]
reserved = header[5:8]
signature_length = int.from_bytes(header[8:12], "big")
if (signature_type != 2 or algorithm != 0 or hash_identifier != 0 or
        signer_length != 0 or key_id_length != 0 or any(reserved)):
    raise SystemExit(11)
# Match Linux mod_check_sig(): sig_len must be strictly smaller than the
# bytes before struct module_signature, not merely fit without underflow.
if signature_length <= 0 or signature_length >= header_offset:
    raise SystemExit(11)
signature_offset = header_offset - signature_length
Path(sys.argv[2]).write_bytes(module[:signature_offset])
Path(sys.argv[3]).write_bytes(module[signature_offset:header_offset])
PY
}

write_public_certificate_pem() {
    local output="$1"
    if (( cert_requires_sudo == 1 )); then
        "${sudo_command[@]}" openssl x509 -inform DER -in "$cert" \
            -outform PEM 2>/dev/null > "$output"
    else
        openssl x509 -inform DER -in "$cert" -outform PEM \
            -out "$output" 2>/dev/null
    fi
}

verify_module_signature() {
    local temp_dir payload_path signature_path certificate_pem
    local extract_rc=0 command_rc=0
    signature_command_status=0

    temp_dir="$(mktemp -d)" || command_rc=$?
    if (( command_rc != 0 )); then
        signature_command_status="$command_rc"
        return 20
    fi
    chmod 0700 "$temp_dir" || command_rc=$?
    if (( command_rc != 0 )); then
        signature_command_status="$command_rc"
        rm -rf -- "$temp_dir"
        return 20
    fi
    payload_path="$temp_dir/module.payload"
    signature_path="$temp_dir/module.p7s"
    certificate_pem="$temp_dir/certificate.pem"

    extract_module_signature "$payload_path" "$signature_path" ||
        extract_rc=$?
    if (( extract_rc != 0 )); then
        signature_command_status="$extract_rc"
        rm -rf -- "$temp_dir"
        return "$extract_rc"
    fi

    command_rc=0
    write_public_certificate_pem "$certificate_pem" || command_rc=$?
    if (( command_rc != 0 )); then
        signature_command_status="$command_rc"
        rm -rf -- "$temp_dir"
        return 20
    fi

    # CMS may contain a foreign signer certificate. Ignore embedded certs:
    # only the configured enrolled MOK certificate may verify this payload.
    command_rc=0
    openssl cms -verify -binary -nointern -inform DER -in "$signature_path" \
        -content "$payload_path" -certfile "$certificate_pem" -noverify \
        -out /dev/null >/dev/null 2>&1 || command_rc=$?
    if (( command_rc != 0 )); then
        signature_command_status="$command_rc"
        rm -rf -- "$temp_dir"
        return 12
    fi

    rm -rf -- "$temp_dir"
    return 0
}
signature_command_status=0
signature_status=0
if verify_module_signature; then
    signature_status=0
else
    signature_status=$?
fi

if [[ "$mode" == verify ]]; then
    case "$signature_status" in
        0)
            printf '%s\n' \
                "Secure Boot: dm-swapz.ko cryptographic signature verified against the enrolled configured MOK; kernel acceptance is not claimed without a safe load"
            exit 0
            ;;
        10)
            blocked_phase detached_signature "$signature_command_status" \
                "qualified module is unsigned"
            ;;
        11)
            blocked_phase detached_signature "$signature_command_status" \
                "qualified module has malformed signing metadata"
            ;;
        12)
            blocked_phase detached_signature "$signature_command_status" \
                "qualified module signature is not cryptographically valid for the configured MOK certificate"
            ;;
        *)
            blocked_phase detached_signature "$signature_command_status" \
                "qualified module signature verification failed"
            ;;
    esac
fi

if (( signature_status == 0 )); then
    restore_build_module_owner
    printf '%s\n' \
        "Secure Boot: dm-swapz.ko already has a cryptographically valid signature from the enrolled configured MOK"
    exit 0
fi
(( signature_status == 10 )) ||
    blocked_phase detached_signature "$signature_command_status" \
        "existing module signature is malformed, invalid, or from a different certificate; refusing to append another signature"

sign=(kmodsign sha512 "$key" "$cert" "$module")
signature_generation_status=0
if [[ -r "$key" ]]; then
    [[ -f "$key" && ! -L "$key" ]] ||
        blocked_phase signature_generation 1 \
            "MOK private key is not a regular file"
    "${sign[@]}" >/dev/null 2>&1 || signature_generation_status=$?
    if (( signature_generation_status != 0 )); then
        blocked_phase signature_generation "$signature_generation_status" \
            "kmodsign failed"
    fi
else
    need_sudo
    "${sudo_command[@]}" test -f "$key" &&
        "${sudo_command[@]}" test ! -L "$key" ||
        blocked_phase signature_generation 1 \
            "MOK private key is missing, unsafe, or sudo authorization is unavailable"
    "${sudo_command[@]}" "${sign[@]}" >/dev/null 2>&1 ||
        signature_generation_status=$?
    if (( signature_generation_status != 0 )); then
        blocked_phase signature_generation "$signature_generation_status" \
            "sudo kmodsign failed or authorization is unavailable"
    fi
fi

if ! verify_module_signature; then
    blocked_phase detached_signature "$signature_command_status" \
        "new module signature failed cryptographic verification against the enrolled configured MOK"
fi
restore_build_module_owner
printf '%s\n' \
    "Secure Boot: signed dm-swapz.ko and cryptographically verified it against the enrolled configured MOK"
