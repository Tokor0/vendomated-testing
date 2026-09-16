*** Settings ***
Documentation    Tests for the Vendomatic toy Python library.
...              This is for the purpose of studying Robot Framework.

Library          vendomatic.machine.VendingMachine    service_pin=1234


*** Test Cases ***
Machine Starts Empty And Locked
    ${s} =    Status
    Log To Console   \nSTATUS: ${s}
    Should Be Equal As Integers    ${s}[slots]    0
    Should Be True    ${s}[locked]

