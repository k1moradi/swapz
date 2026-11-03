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

command -v modinfo >/dev/null 2>&1 || blocked "modinfo is required"
command -v openssl >/dev/null 2>&1 || blocked "openssl is required"
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

normalize_hex() {
    tr -d ':[:space:]' | tr '[:lower:]' '[:upper:]'
}

cert_requires_sudo=0
if [[ -r "$cert" ]]; then
    [[ -f "$cert" && ! -L "$cert" ]] ||
        blocked "MOK certificate is not a regular file"
    cert_serial="$(openssl x509 -inform DER -in "$cert" -noout -serial 2>/dev/null |
                   sed -n 's/^serial=//p' | normalize_hex)"
else
    if [[ "$mode" == verify ]]; then
        blocked "MOK certificate is unavailable for signature verification"
    fi
    need_sudo
    "${sudo_command[@]}" test -f "$cert" &&
        "${sudo_command[@]}" test ! -L "$cert" ||
        blocked "MOK certificate is missing, unsafe, or sudo authorization is unavailable"
    cert_requires_sudo=1
    cert_serial="$("${sudo_command[@]}" openssl x509 -inform DER -in "$cert" \
                     -noout -serial 2>/dev/null |
                   sed -n 's/^serial=//p' | normalize_hex)"
fi
[[ -n "$cert_serial" ]] || blocked "cannot read MOK certificate serial"

command -v mokutil >/dev/null 2>&1 ||
    blocked "mokutil is required to verify MOK enrollment"
if (( cert_requires_sudo == 1 )); then
    "${sudo_command[@]}" mokutil --test-key "$cert" >/dev/null 2>&1 ||
        blocked "configured MOK certificate is not enrolled"
else
    mokutil --test-key "$cert" >/dev/null 2>&1 ||
        blocked "configured MOK certificate is not enrolled"
fi

module_sig_key="$(modinfo -F sig_key "$module" 2>/dev/null | normalize_hex)"
if [[ -n "$module_sig_key" && "$module_sig_key" == "$cert_serial" ]]; then
    if [[ "$mode" == verify ]]; then
        printf '%s\n' "Secure Boot: qualified dm-swapz.ko signature verified"
    else
        printf '%s\n' "Secure Boot: dm-swapz.ko already signed with configured MOK"
    fi
    exit 0
fi

[[ "$mode" == sign ]] ||
    blocked "qualified module is unsigned or signed by a different key"

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

module_sig_key="$(modinfo -F sig_key "$module" 2>/dev/null | normalize_hex)"
[[ "$module_sig_key" == "$cert_serial" ]] ||
    blocked "module signature does not match configured MOK after signing"
printf '%s\n' "Secure Boot: signed dm-swapz.ko with configured MOK"
