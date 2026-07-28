/*
 * Copyright (c) Valkey Contributors
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 */

/*
 * Intentional failure suite for the gtest path. It exercises the CI
 * test-failure detector against the GoogleTest unit suite
 * (src/unit/valkey-unit-gtests), which the Daily workflow's "unittest"
 * step runs and whose JSON results feed the extract-gtest-failures action.
 *
 * This is not a real test of any code path. Remove it once the detector
 * has been validated.
 */

#include "generated_wrappers.hpp"

#include <cstdlib>
#include <cstring>

extern bool valgrind;

class DummyTest : public ::testing::Test {};

TEST_F(DummyTest, BasicPasses) {
    EXPECT_EQ(1 + 1, 2);
    EXPECT_STREQ("myvalue", "myvalue");
}

/* Intentional assertion failure: surfaces as a gtest FAIL in the JSON. */
TEST_F(DummyTest, IntentionalFailure) {
    const char *got = "myvalue";
    EXPECT_STREQ(got, "wrongvalue");
}

TEST_F(DummyTest, AnotherPasses) {
    int counter = 0;
    counter++;
    EXPECT_EQ(counter, 1);
}

/* Intentional memory leak: only flagged under valgrind/ASan. */
TEST_F(DummyTest, IntentionalLeakUnderValgrind) {
    void *leaked = malloc(64);
    ASSERT_NE(leaked, nullptr);
    memset(leaked, 'x', 64);
    /* Deliberately drop `leaked` without free(). */
    if (!valgrind) {
        SUCCEED();
    }
}
