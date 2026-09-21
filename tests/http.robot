*** Settings ***
Documentation    HTTP API tests for Vendomatic.

Resource         ../resources/http.resource

Test Setup       Start New Server
Test Teardown    Stop Server
Test Timeout     30 seconds


*** Test Cases ***
Health Reports OK
    [Documentation]    Check that the server is healthy.
    Server Should Be Healthy
