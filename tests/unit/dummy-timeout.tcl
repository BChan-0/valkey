# Intentional timeout for test-failure detector validation.
# This test sleeps longer than the test framework's per-test timeout,
# triggering the "timeout" failure type in the JSON artifact.
#
# The default framework timeout is 1200s (20 min). This test uses
# a blocking wait that will exceed any reasonable CI timeout threshold.
# In practice the test_server_cron detects the hang after ::timeout seconds.

start_server {tags {"dummy"}} {
    test "dummy-timeout - passing sanity check" {
        r SET key val
        assert_equal [r GET key] "val"
    }

    test "dummy-timeout - intentional hang exceeding timeout" {
        # Block the client for 5 minutes. Under CI with a short timeout this
        # will be killed by test_server_cron and reported as [TIMEOUT].
        # Use BLPOP on a non-existent key to block without busy-spinning.
        r BLPOP __nonexistent_key_for_timeout_test__ 300
    }
}