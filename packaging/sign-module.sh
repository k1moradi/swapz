#!/usr/bin/env bash
# Sign qualification modules at build time; packaging uses --verify only.
set -Eeuo pipefail

blocked() {
    printf 'BLOCKED: Secure Boot module signing: %s\n' "$*" >&2
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
    blocked "built dm-swapz.ko is missing or not a regular file"

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
    blocked "cannot determine EFI Secure Boot state"

key="${SWAPZ_MOK_PRIVATE_KEY:-/var/lib/shim-signed/mok/MOK.priv}"
cert="${SWAPZ_MOK_CERT:-/var/lib/shim-signed/mok/MOK.der}"

command -v openssl >/dev/null 2>&1 || blocked "openssl is required"
command -v python3 >/dev/null 2>&1 || blocked "python3 is required"
command -v mktemp >/dev/null 2>&1 || blocked "mktemp is required"
if [[ "$mode" == sign ]]; then
    command -v kmodsign >/dev/null 2>&1 || blocked "kmodsign is required"
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
        blocked "MOK certificate is unavailable for signature verification"
    fi
    need_sudo
    "${sudo_command[@]}" test -f "$cert" &&
        "${sudo_command[@]}" test ! -L "$cert" ||
        blocked "MOK certificate is missing, unsafe, or sudo authorization is unavailable"
    cert_requires_sudo=1
fi

command -v mokutil >/dev/null 2>&1 ||
    blocked "mokutil is required to verify MOK enrollment"
if (( cert_requires_sudo == 1 )); then
    "${sudo_command[@]}" mokutil --test-key "$cert" >/dev/null 2>&1 ||
        blocked "configured MOK certificate is not enrolled"
else
    mokutil --test-key "$cert" >/dev/null 2>&1 ||
        blocked "configured MOK certificate is not enrolled"
fi

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
signature_type = header[2]
signer_length = header[3]
key_id_length = header[4]
signature_length = int.from_bytes(header[8:12], "big")
if signature_type != 2 or signer_length != 0 or key_id_length != 0:
    raise SystemExit(11)
signature_offset = header_offset - signature_length
if signature_length <= 0 or signature_offset < 0:
    raise SystemExit(11)
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
    local temp_dir payload_path signature_path certificate_pem extract_rc=0
    temp_dir="$(mktemp -d)" || return 20
    chmod 0700 "$temp_dir" || {
        rm -rf -- "$temp_dir"
        return 20
    }
    payload_path="$temp_dir/module.payload"
    signature_path="$temp_dir/module.p7s"
    certificate_pem="$temp_dir/certificate.pem"

    extract_module_signature "$payload_path" "$signature_path" ||
        extract_rc=$?
    if (( extract_rc != 0 )); then
        rm -rf -- "$temp_dir"
        return "$extract_rc"
    fi
    write_public_certificate_pem "$certificate_pem" || {
        rm -rf -- "$temp_dir"
        return 20
    }
    openssl cms -verify -binary -inform DER -in "$signature_path" \
        -content "$payload_path" -certfile "$certificate_pem" -noverify \
        -out /dev/null >/dev/null 2>&1 || {
        rm -rf -- "$temp_dir"
        return 12
    }
    rm -rf -- "$temp_dir"
    return 0
}

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
            blocked "qualified module is unsigned"
            ;;
        11)
            blocked "qualified module has malformed signing metadata"
            ;;
        12)
            blocked "qualified module signature is not cryptographically valid for the configured MOK certificate"
            ;;
        *)
            blocked "qualified module signature verification failed"
            ;;
    esac
fi

if (( signature_status == 0 )); then
    printf '%s\n' \
        "Secure Boot: dm-swapz.ko already has a cryptographically valid signature from the enrolled configured MOK"
    exit 0
fi
(( signature_status == 10 )) ||
    blocked "existing module signature is malformed, invalid, or from a different certificate; refusing to append another signature"

sign=(kmodsign sha512 "$key" "$cert" "$module")
if [[ -r "$key" ]]; then
    [[ -f "$key" && ! -L "$key" ]] ||
        blocked "MOK private key is not a regular file"
    "${sign[@]}" || blocked "kmodsign failed"
else
    need_sudo
    "${sudo_command[@]}" test -f "$key" &&
        "${sudo_command[@]}" test ! -L "$key" ||
        blocked "MOK private key is missing, unsafe, or sudo authorization is unavailable"
    "${sudo_command[@]}" "${sign[@]}" ||
        blocked "sudo kmodsign failed or authorization is unavailable"
fi

verify_module_signature ||
    blocked "new module signature failed cryptographic verification against the enrolled configured MOK"
printf '%s\n' \
    "Secure Boot: signed dm-swapz.ko and cryptographically verified it against the enrolled configured MOK"
