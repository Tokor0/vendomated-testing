*** Settings ***
Documentation    Keyword resource for testing the Vendomatic toy Python library.
...              This is for the purpose of studying Robot Framework.
Library          vendomatic.machine.VendingMachine    service_pin=${SERVICE_PIN}

*** Variables ***
${SERVICE_PIN}     1234
${ALT_PIN}         4321
@{INVALID_PINS}    999    10000    asdf    -1234    -999    -10000

*** Keywords ***
Unlock Machine
    [Arguments]    ${pin}=${SERVICE_PIN}
    Unlock    ${pin}

Machine Should Be Locked
    ${s} =    Status
    Should Be True    ${s}[locked]

Machine Should Be Unlocked
    ${s} =    Status
    Should Not Be True    ${s}[locked]

Machine Should Have N Slots
    [Arguments]    ${N}
    ${s} =    Status
    Should Be Equal As Integers    ${s}[slots]    ${N}
