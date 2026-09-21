*** Settings ***
Documentation    Keyword resource for testing Vendomatic's HTTP API.

Library          OperatingSystem
Library          Process
Library          RequestsLibrary


*** Variables ***
${ALIAS}          vendomatic
${ADMIN_ALIAS}    vendomatic-admin
${PROC_ALIAS}     vendomatic-server
${HOST}           127.0.0.1
${PORT}           8123
${TOKEN}          service-token
${URL}            http://${HOST}:${PORT}
${SERVE_LOG}      ${TEMPDIR}${/}vendomatic-serve.out
${STATE_FILE}     ${TEMPDIR}${/}vendomatic-http-state.json

@{VALID_COINS}    ${5}    ${10}    ${25}    ${100}
@{INVALID_COINS}    5    ${7}    ${125}    ${-5}


*** Keywords ***
Start New Server
    [Documentation]    Reset state file, then start the API and open sessions.
    Run Process    python    -m    vendomatic    reset    --state    ${STATE_FILE}
    Start Process    python    -m    vendomatic    serve
    ...    --host    ${HOST}    --port    ${PORT}    --token    ${TOKEN}    --state    ${STATE_FILE}
    ...    stdout=${SERVE_LOG}    stderr=STDOUT    alias=${PROC_ALIAS}
    ${admin_headers} =    Create Dictionary    X-Service-Token=${TOKEN}
    Create Session    ${ALIAS}    ${URL}
    Create Session    ${ADMIN_ALIAS}    ${URL}    headers=${admin_headers}
    Wait Until Keyword Succeeds    20x    250ms    Server Should Be Healthy

Server Should Be Healthy
    [Documentation]    Gets the server's health endpoint. Expects status to be ok.
    ${resp} =    GET On Session    ${ALIAS}    /health    expected_status=200
    ${body} =    Set Variable    ${resp.json()}
    Should Be Equal    ${body}[status]    ok

Stop Server
    [Documentation]    Terminate the server process and delete HTTP sessions.
    Terminate Process    ${PROC_ALIAS}
    Wait For Process    ${PROC_ALIAS}    timeout=5s
    Delete All Sessions

Purchase
    [Documentation]    Attempts to purchase from a slot.
    [Arguments]    ${slot}    ${expected_status}=200
    ${json} =    Create Dictionary    code=${slot}
    ${resp} =    POST On Session    ${ALIAS}    /purchase    expected_status=${expected_status}
    ...    json=${json}
    ${body} =    Set Variable    ${resp.json()}
    Return From Keyword    ${body}

# Quite a lot of boilerplate... Figure out a better way to get the body
Insert Coin
    [Documentation]    Attempts to insert a coin.
    [Arguments]    ${value}    ${expected_status}=201
    ${json} =    Create Dictionary    value=${value}
    ${resp} =    POST On Session    ${ALIAS}    /coins    expected_status=${expected_status}
    ...    json=${json}
    ${body} =    Set Variable    ${resp.json()}
    Return From Keyword    ${body}

