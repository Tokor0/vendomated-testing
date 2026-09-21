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
    [Documentation]    Unlocks the vending maching. Uses SERVICE_PIN by default.
    [Arguments]    ${pin}=${SERVICE_PIN}
    Unlock    ${pin}

Unlock Should Be Denied On Wrong PIN
    [Documentation]    Attempts to unlock the machine. Expects an incorrect PIN error.
    [Arguments]    ${pin}
    Run Keyword And Expect Error    *Incorrect service PIN    Unlock    ${pin}

Machine Should Be Locked
    [Documentation]    Checks that the machine is locked.
    ${s} =    Status
    Should Be True    ${s}[locked]

Machine Should Be Unlocked
    [Documentation]    Checks that the machine is unlocked.
    ${s} =    Status
    Should Not Be True    ${s}[locked]

Machine Should Have N Slots
    [Documentation]    Checks that the machine has exactly N slots.
    [Arguments]    ${N}
    ${s} =    Status
    Should Be Equal As Integers    ${s}[slots]    ${N}

Service Operation Should Be Denied
    [Documentation]    Attempts op with args, expects a MachineLockedError.
    [Arguments]    ${op}    @{args}
    Run Keyword And Expect Error    MachineLockedError*    ${op}    @{args}

Invalid Value Should Be Denied
    [Documentation]    Attempts op with args, expects a ValueError.
    [Arguments]    ${op}    @{args}
    Run Keyword And Expect Error    ValueError*    ${op}    @{args}
