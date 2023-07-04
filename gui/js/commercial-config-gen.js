// Toggle BGP form for commercial INET form
function toggleBgpForm() {
    let bgpForm = $('#cardBgp');
    if ($('#protocolBgp').is(':checked')) {
        $('#cardBgp').show();
        $('#cardBgp :input').prop('required', true);
    } else {
        $('#cardBgp').hide();
        $('#cardBgp :input').prop('required', false);
    }
}

// Generates interface description for commercial INET & TLS form
function generateDescription() {
    let customer = document.getElementById('customer').value;
    let bandwidth = document.getElementById('bandwidth').value;
    let circuitId = document.getElementById('circuitId').value;
    let formType = location.href.split("/").slice(-1)[0];
    let spacer, circuitType;

    switch (formType) {
        case 'internet':
            spacer = '.............D....... ';
            circuitType = 'Internet';
            break;
        case 'transparent_lan':
            spacer = '.............T....... ';
            circuitType = 'TLS';
            break;
        case 'vpls':
            spacer = '...............V..... ';
            circuitType = 'VPLS';
    }
    return spacer.concat(customer, ' - ', bandwidth, 'M ', circuitType, ' - ', circuitId);
}


// Generates BGP password for commercial INET form
function generateBgpPassword() {
    let customerSplit = document.getElementById('customer').value.split(' ');
    let circuitSplit = document.getElementById('circuitId').value.split('-');
    let customerInitials = '';

    // If customer name is 1 word, use the first 3 initials. Otherwise, use initials of whole customer name.
    if (customerSplit.length == 1) {
        customerInitials = customerSplit[0].slice(0, 3).toUpperCase();
    } else {
        for (let i = 0; i < customerSplit.length; i++) {
            customerInitials += customerSplit[i].charAt(0);
        }
    }

    let bgpPassword = customerInitials + circuitSplit[0] + circuitSplit[2];
    document.getElementById('bgpPwd').value = bgpPassword
}

// Populate Raisecom ports and update port speed options
$('#model').change(function () {
    var portSelect = { '#uplinkPort': 'uplink_ports', '#clientPort': 'client_ports' }

    $.each(portSelect, function (selectId, dbColumn) {
        $(selectId + ' option').remove()
        let ports = raisecomDb[$('#model').val()][dbColumn]
        $.each(ports, function (index, port) {
            $(selectId).append(new Option(port, port));
        })
    })
    // Add/remove 10G port speed option
    if (raisecomDb[$('#model').val()]['bandwidth'] === '10G') {
        $('#portSpeed').prepend(new Option('10000M', '10000M'))
    } else {
        $("#portSpeed option[value='10000M']").remove()
    }
});

// Toggle on spinner for fetch functions
function toggleFetchSpinner() {
    $('.modal').modal('hide')
    $('.spinner-border').show()
    $('.alert').html('').hide()
}

// Toggles spinner and alert displaying the message
function showFetchResults(result, message) {
    $('.spinner-border').hide()
    $('.alert').html(message).show()
    if (result) {
        $('.alert').addClass('alert-success')
        $('.alert').removeClass('alert-danger')
    } else {
        $('.alert').addClass('alert-danger')
        $('.alert').removeClass('alert-success')
    }
}

// Generates a layer 2 name (e.g. pseudowire, VPLS bd-name) using with customer and circuit ID
function generateL2Name() {
    let customerShortened = $('#customer').val().replace(/ /g, '');
    let circuitSplit = $('#circuitId').val().split('-').slice(0, 3);

    return customerShortened + '_' + circuitSplit.join('')
}

// Event Listeners //

// Generate pseudowire name
$('#generatePwName').click(function () { 
    $('#pwName').val(generateL2Name()).trigger('change');
})

// Generate bridge-domain name
$('#bdNameButton').click(function () { 
    $('#bdName').val(generateL2Name()).trigger('change'); 
})

// Generate circuit description
$('#descriptionButton').click(function () { 
    $('#description').val(generateDescription()) 
    $('#description').trigger('change')
})

// Fetch available pseudowire ID
$('#pwIdBtn').click(async function () {
    toggleFetchSpinner()
    let data = new FormData();
    data.append('routerA', $('#routerA').val())
    data.append('routerZ', $('#routerZ').val())

    try {
        let response = await fetch('/get-pw-id', {
            method: 'POST',
            body: data
        });

        let pwId = await response.json();
        showFetchResults(true, `Next available pseudowire is: ${pwId}`)
        $('#pwId').val(pwId)
    } catch (error) {
        showFetchResults(false, 'Error fetching pseudowire ID')
    }
})

// Verify VPN ID
$('#vpnIdBtn').click(async function () {
    toggleFetchSpinner();
    vpnId = $( '#vpnId' ).val()
    try {
        let response = await fetch('/verify-vpn-id', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(vpnId)
        })

        let result = await response.json();
        if (result) {
            showFetchResults(true, `Verified! VPN ID: ${vpnId} is available.`)
        } else {
            showFetchResults(false, `<strong>WARNING!</strong> Found VPN ID: ${vpnId} on the route reflector.`)
        }

    } catch(error) {
        console.log(error)
        showFetchResults(false, 'Error validating VPN ID (has not been checked)')
    }
})

