/* SPDX-License-Identifier: GPL-2.0-only */
/* Host-only white-box fault injection. Compile the real bridge exactly once.
 * No production setter, no model of the terminal predicates, no native credit.
 */
#include "native-observation-byte-bridge.c"

void round108_terminal_probe(const char *mode)
{
	bool late = !strcmp(mode, "late_finish_internal");
	bool pending = !strcmp(mode, "close_pending");
	bool committed = !strcmp(mode, "close_committed");

	if (!late && !pending && !committed)
		return;
	/* Public APIs cannot create this state after a valid CLEANUP. Inject
	 * residual private debt only to test the independent defensive gates.
	 * The single-threaded fixture owns all producers here. */
	assert(bridge && bridge->cleaned && !bridge->loss);
	struct staged_input *input = &bridge->input[0];
	assert(!input->token && !input->committed);
	if (committed) {
		input->committed = true;
		return;
	}
	input->token = 123;
	if (late) {
		u64 store = input->store;
		unsigned int bank = input->bank;

		swapz_trial_byte_finish_input(123, store + 1U);
		assert(bridge->loss && input->token == 123 && input->store == store &&
		       input->bank == bank && !input->committed);
	}
}
