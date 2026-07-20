# Intentional server startup failure for test-failure detector validation.
# This suite triggers the "startup" failure type by attempting to start a
# server on a port that is already occupied by the outer server.

start_server {tags {"dummy"}} {
    test "dummy-startup - passing sanity check" {
        r SET key val
        assert_equal [r GET key] "val"
    }

    # Start a nested server on the SAME port as the outer server.
    # This will fail with "Failed listening on port" / "Can't start".
    set port [srv 0 port]
    start_server [list overrides [list port $port]] {
        test "dummy-startup - this should not be reached" {
            fail "Server should not have started"
        }
    }
}