# Intentional timeout for test-failure detector validation.
# This test uses an infinite BLPOP so the framework's test_server_cron
# detects the hang and reports it as [TIMEOUT].
#
# Requires passing --timeout 5 (or similar short value) in test_args
# so the framework kills it quickly rather than waiting 20 minutes.

start_server {tags {"dummy"}} {
    test "dummy-timeout - passing sanity check" {
        r SET key val
        assert_equal [r GET key] "val"
    }

    test "dummy-timeout - intentional hang exceeding timeout" {
        # BLPOP 0 blocks indefinitely. The framework's test_server_cron
        # will kill this client after ::timeout seconds and report [TIMEOUT].
        r BLPOP __nonexistent_key_for_timeout_test__ 0
    }
}
