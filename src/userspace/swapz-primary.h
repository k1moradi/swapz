/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PRIMARY_H
#define SWAPZ_PRIMARY_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

enum swapz_primary_stage {
	SWAPZ_PRIMARY_STAGE_READY = 0,
	SWAPZ_PRIMARY_STAGE_STARTING,
	SWAPZ_PRIMARY_STAGE_ACTIVE,
	SWAPZ_PRIMARY_STAGE_STOPPING,
	SWAPZ_PRIMARY_STAGE_RECOVERING,
	SWAPZ_PRIMARY_STAGE_RESTORED,
	SWAPZ_PRIMARY_STAGE_DISABLING,
	SWAPZ_PRIMARY_STAGE_COMPLETE,
	SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED,
	SWAPZ_PRIMARY_STAGE_COUNT
};

#define SWAPZ_PRIMARY_RUN_ID_LENGTH 32U
#define SWAPZ_PRIMARY_SOURCE_SHA_LENGTH 40U
#define SWAPZ_PRIMARY_SHA256_LENGTH 64U

struct swapz_primary_state {
	char run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U];
	enum swapz_primary_stage stage;
	int has_recovery_previous_stage;
	enum swapz_primary_stage recovery_previous_stage;
};

struct swapz_primary_manifest {
	char run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U];
	char source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 1U];
	char swapzctl_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
	char module_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
	char qualification_report_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
	char original_header_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
};

struct swapz_primary_qualification {
	char source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 1U];
	char host_identity_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
	char formatter_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
	char module_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
	char oracle_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
	char report_sha256[SWAPZ_PRIMARY_SHA256_LENGTH + 1U];
};

const char *swapz_primary_stage_name(enum swapz_primary_stage stage);
int swapz_primary_stage_parse(const char *name,
			      enum swapz_primary_stage *stage);
int swapz_primary_stage_transition_allowed(enum swapz_primary_stage from,
						   enum swapz_primary_stage to);
int swapz_primary_state_parse(const char *record, size_t length,
			      struct swapz_primary_state *state);
int swapz_primary_state_format(const struct swapz_primary_state *state,
			       char *record, size_t capacity);
int swapz_primary_state_transition_allowed(
	const struct swapz_primary_state *current,
	const struct swapz_primary_state *next);
/* Mint a cryptographically random lowercase 32-hex-character transaction ID. */
int swapz_primary_run_id_generate(
	char run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U]);
/* Build the exact fixed-geometry SWZ authorization header for a run ID. */
int swapz_primary_header_build(
	const char run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U],
	unsigned char header[4096]);
int swapz_primary_manifest_parse(const char *record, size_t length,
				 struct swapz_primary_manifest *manifest);
/* Validate the exact five-stage owner report for this source and host. */
int swapz_primary_qualification_parse_json(
	const unsigned char *json, size_t length, const char *expected_source_sha,
	const char *expected_host_identity_sha256,
	struct swapz_primary_qualification *qualification);
int swapz_primary_manifest_format(
	const struct swapz_primary_manifest *manifest, char *record,
	size_t capacity);
int swapz_primary_manifest_write_at(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest, uid_t expected_owner);
int swapz_primary_manifest_read_at(
	int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner,
	struct swapz_primary_manifest *manifest);
/* Open only the fixed, identity-checked /dev/sda4 target, exclusively. */
int swapz_primary_target_open_exclusive(void);
/* Production callers must open the target O_RDWR|O_EXCL before calling. */
int swapz_primary_write_header_checked_fd(
	int fd, const unsigned char expected_current[4096],
	const unsigned char replacement[4096]);
/* Hash a stable, private regular-file descriptor with bounded allocation. */
int swapz_primary_sha256_regular_fd(int fd, uid_t expected_owner,
				    uint64_t maximum_bytes, char digest[65]);
/* Open the exact packaged module beside this control binary and pin its bytes.
 * The returned read-only descriptor must be used directly for finit_module. */
int swapz_primary_open_qualified_module_fd(
	const char *control_executable, const char expected_sha256[65]);
/* Caller must durably own a STARTING transaction before requesting this load.
 * loaded_by_call remains true if post-load verification subsequently fails. */
int swapz_primary_load_qualified_module(int *loaded_by_call);
/*
 * These Device Mapper lifecycle primitives are not enabled by the public
 * primary-swap command until the complete coordinator is qualified.
 * `module_loaded_by_call` must come directly from the exact-image loader.
 */
int swapz_primary_dm_create_mapper(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	int module_loaded_by_call, int *created_by_call,
	int *resumed_by_call, dev_t *mapper_device);
int swapz_primary_dm_remove_mapper(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	int *removed_by_call);

int swapz_primary_partition_lock_acquire(void);
/* Internal lifecycle primitive; caller must hold the matching partition lock. */
int swapz_primary_claim_partition_owner_at(int recovery_fd, int lock_fd,
						  const char *run_id,
						  uid_t expected_owner);
/* Atomically replace a durable state record while holding the partition lock. */
int swapz_primary_replace_record_at(int recovery_fd, const char *name,
				    const char *run_id, const char *record,
				    uid_t expected_owner);
/* State changes require the exclusive partition lock and current run claim. */
int swapz_primary_state_write_at(int recovery_fd, int lock_fd,
				 const struct swapz_primary_state *next,
				 uid_t expected_owner);
/* Save/read the run's immutable exact 4096-byte original partition header. */
int swapz_primary_header_backup_write_at(
	int recovery_fd, int lock_fd, const char *run_id,
	const unsigned char header[4096], const char *expected_sha256,
	uid_t expected_owner);
int swapz_primary_header_backup_read_at(
	int recovery_fd, int lock_fd, const char *run_id,
	const char *expected_sha256, uid_t expected_owner,
	unsigned char header[4096]);
/* Only a COMPLETE state may release the active marker; consumed claim remains. */
int swapz_primary_release_partition_owner_at(int recovery_fd, int lock_fd,
						     const char *run_id,
						     uid_t expected_owner);
int swapz_primary_command(int argc, char **argv);

#endif /* SWAPZ_PRIMARY_H */
