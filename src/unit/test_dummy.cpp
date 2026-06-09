/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/*
 * Intentional failure suite for the gtest path, mirroring the TCL
 * dummy-flaky.tcl / dummy-memory.tcl triggers. It exists to exercise the CI
 * test-failure detector against the GoogleTest unit suite
 * (src/unit/valkey-unit-gtests, run by `make test-unit` in the Daily
 * workflow's "unittest" step and under valgrind in test-valgrind-misc).
 *
 * It is NOT a real test of any code path. Keep it out of unstable once the
 * detector has been validated, the same way the dummy-*.tcl suites are
 * temporary.
 */

#include "generated_wrappers.hpp"

#include <cstdlib>
#include <cstring>

// `valgrind` is set from the --valgrind flag parsed in main.cpp; reuse it so
// the leak case below only fires where something actually inspects for leaks.
extern bool valgrind;

class DummyTest : public ::testing::Test {};

// Passing test - the suite should still report this as a pass.
TEST_F(DummyTest, BasicPasses) {
    EXPECT_EQ(1 + 1, 2);
    EXPECT_STREQ("myvalue", "myvalue");
}

// Intentional failure - a genuine gtest assertion failure (not a faked one),
// so it surfaces in the failures report exactly the way a real bug would.
// This is the gtest analogue of dummy-flaky.tcl's "intentional failure" test.
TEST_F(DummyTest, IntentionalFailure) {
    const char *got = "myvalue";
    EXPECT_STREQ(got, "wrongvalue");
}

// Another passing test, to confirm the runner keeps going after a failure.
TEST_F(DummyTest, AnotherPasses) {
    int counter = 0;
    counter++;
    EXPECT_EQ(counter, 1);
}

// Intentional memory error, mirroring dummy-memory.tcl. The allocation is
// leaked on purpose: under a normal `make test-unit` nothing inspects for it
// and the test passes, but under `make valgrind` / the test-valgrind-misc job
// (valkey-unit-gtests run with --leak-check=full) or an AddressSanitizer build
// it shows up as a "definitely lost" / leak report - a real memory error, not
// a faked assertion.
TEST_F(DummyTest, IntentionalLeakUnderValgrind) {
    void *leaked = malloc(64);
    ASSERT_NE(leaked, nullptr);
    memset(leaked, 'x', 64);
    // Deliberately drop `leaked` without free() so leak detectors flag it.
    if (!valgrind) {
        // Outside a leak-checking run there is nothing to assert on; just
        // confirm the suite executed.
        SUCCEED();
    }
}
