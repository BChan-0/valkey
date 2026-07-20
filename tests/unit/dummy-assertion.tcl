# Intentional assertion failure for test-failure detector validation.
# This suite triggers the "assertion" failure type in the JSON artifact.

start_server {tags {"dummy"}} {
    test "dummy-assertion - basic SET and GET passes" {
        r SET mykey myvalue
        assert_equal [r GET mykey] "myvalue"
    }

    test "dummy-assertion - intentional assertion failure" {
        r SET mykey myvalue
        assert_equal [r GET mykey] "wrongvalue"
    }

    test "dummy-assertion - another passing test" {
        r SET counter 0
        r INCR counter
        assert_equal [r GET counter] "1"
    }
}