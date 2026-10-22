#!/usr/bin/env bash
# Sign the normal swapz qualification module when EFI Secure Boot is enabled.
set -Eeuo pipefail

blocked() {
    printf 'BLOCKED: Secure Boot module signing: %s\n' "$*" >&2
    exit 2
}

[[ $# == 1 ]] || blocked "internal helper requires exactly one module path"
module="$1"
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

command -v modinfo >/dev/null 2>&1 ||
    blocked "modinfo is required"
command -v openssl >/dev/null 2>&1 ||
    blocked "openssl is required"
command -v kmodsign >/dev/null 2>&1 ||
    blocked "kmodsign is required"

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

if [[ -r "$cert" ]]; then
    [[ -f "$cert" && ! -L "$cert" ]] ||
        blocked "MOK certificate is not a regular file"
    cert_serial="$(openssl x509 -inform DER -in "$cert" -noout -serial 2>/dev/null |
                   sed -n 's/^serial=//p' | normalize_hex)"
else
    need_sudo
    "${sudo_command[@]}" test -f "$cert" &&
        "${sudo_command[@]}" test ! -L "$cert" ||
        blocked "MOK certificate is missing, unsafe, or sudo authorization is unavailable"
    cert_serial="$("${sudo_command[@]}" openssl x509 -inform DER -in "$cert"                     -noout -serial 2>/dev/null |
                   sed -n 's/^serial=//p' | normalize_hex)"
fi
[[ -n "$cert_serial" ]] ||
    blocked "cannot read MOK certificate serial"

module_sig_key="$(modinfo -F sig_key "$module" 2>/dev/null | normalize_hex)"
if [[ -n "$module_sig_key" && "$module_sig_key" == "$cert_serial" ]]; then
    printf '%s\n' "Secure Boot: dm-swapz.ko already signed with configured MOK"
    exit 0
fi

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
