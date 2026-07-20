# Intentional server startup failure for test-failure detector validation.
# This suite triggers the "startup" failure type ("Can't start") by using
# an invalid configuration directive that causes a FATAL CONFIG FILE ERROR.
# The start_server helper translates this into a "Can't start" error message.

start_server {tags {"dummy"} overrides {invalid-config-key-that-does-not-exist "bogus"}} {
    test "dummy-startup - this should not be reached" {
        fail "Server should not have started with invalid config"
    }
}
