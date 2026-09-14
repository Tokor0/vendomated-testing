*** Settings ***
Documentation    Smoke test proving the editor tooling is wired up.

Library          OperatingSystem


*** Test Cases ***
Environment Variable Should Be Readable
    [Documentation]    Reads HOME via OperatingSystem.
    [Tags]    smoke
    ${home} =    Get Environment Variable    HOME
    Should Not Be Empty    ${home}
