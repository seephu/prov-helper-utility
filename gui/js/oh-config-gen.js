$(document).ready(function () {
    // Populates a dropdown with an array. Takes in a select selector and an array of strings.
    function populateSelect(select, options) {
        $(select).empty();
        $(select).append('<option></option>')
        $.each(options, function (i, value) {
            if (value) {
                $(select).append($('<option></option>').val(value).html(value));
            }
        });
    }

    // Dynamically create service VLANs for OH decom gen
    $('#numServices').change(function () {
        $('#serviceDiv').empty()
        var numServices = $(this).val()
        var card = $('#servicesCard')
        for (let i = 1; i <= numServices; i++) {
            var row = $('#serviceRow').clone().appendTo('#serviceDiv')
            row.find('input').prop('id', 'serviceVlan' + i).prop('name', 'serviceVlan' + i)
            row.find('label').append(i).prop('for', 'serviceVlan' + 1)
            row.show()
            card.append(row)
        }
        $('#serviceRow :input').prop('required', false);
    })

    // Populate service VLANs based off first VLAN input
    $("#serviceDiv").on('keyup', '#serviceVlan1', function () {
        let vlan = parseInt(this.value) + 1;
        for (i = 2; i <= $('#numServices').val(); i++) {
            $('#serviceVlan' + i).val(vlan++).change();
        }
    })

    // Populate VPN VLAN based off NMS
    $('[id^="nmsVlan"]').on('keyup', function () {
        let suffix = '';
        if (this.id.includes('Backup')) {
            // TODO: use whatever existing prefix is, not hardcore backup
            suffix = 'Backup';
        }
        $(`#vpnVlan${suffix}`).val(parseInt(this.value) + 1).change();
        console.log()
    })


    /*
    OH SRX specific scripts
    */

    // Switch between vars file and manual form fields
    $('#formType').on('change', function () {
        if (this.value == 'manual') {
            location.reload();
        } else {
            $('#manualInput').hide()
            $('#varsInput').show()
            $('.progress-bar').show()
            $('#formContent').remove()
            $('#reviewForm').remove()
        }
    })

    // Generate services and appends them to the accordion
    function generateServices(n, siteEle) {
        let serviceDiv = document.getElementById(`service${siteEle}`)
        let accordion = document.getElementById(`accordion${siteEle}`)

        for (let i = 1; i <= n; i++) {
            let clonedService = serviceDiv.cloneNode(true);
            clonedService.setAttribute('id', `service${i}`)

            // Clone all fields and update their labels, names & IDs
            clonedService.querySelectorAll('input, select, textarea').forEach((element) => {
                let name = element.getAttribute('name');
                let id = element.getAttribute('id');
                let label = clonedService.querySelector(`label[for="${id}"]`);

                element.setAttribute('name', `${name}${i}`);
                element.setAttribute('id', `${id}${i}`);
                try {
                    label.setAttribute('for', `${id}${i}`);
                } catch (error) {
                    console.log('No label for input: ' + id)
                }
            });

            // Accordion header
            let accordionHeader = `collapseService${siteEle}${i}`
            clonedService.querySelector('h6').textContent = 'Service #' + i
            clonedService.querySelector('a.card-header').setAttribute('href', '#' + accordionHeader)
            clonedService.querySelector('.collapse').setAttribute('id', accordionHeader)
            accordion.appendChild(clonedService);
        }
        serviceDiv.remove()
    }

    // Generate and display form
    $('#formTypeBtn').on('click', function () {
        let siteType = $('#siteType').val();
        let numServices = $('#numServices').val();
        if (!siteType || !numServices) {
            $('#showFormError').show()
            return
        }

        // Remove backup elements accordingly
        if (siteType === 'single') {
            $('#backup').remove()
            $('#terminalServer').remove()
            $('#clciSuffix').remove()
        } else {
            $('#siteNavPills').show()
        }

        // Display form
        generateServices(numServices, 'Primary');
        if (siteType == 'dual') {
            generateServices(numServices, 'Backup');
        }
        $('#formTypeCard').hide()
        $('#formContent').show()
        $('#reviewForm').show()
    })

    // Populate primary CPE & RETH port dropdowns
    $('#deviceType').on('change', function () {
        // ports var declared in the front-end
        let device = $('#deviceType').val().toLowerCase() + '_primary';
        populateSelect('#cpeReth', PORTS['rethPorts'][device])
        for (let i = 1; i <= $('#numServices').val(); i++) {
            populateSelect('#serviceCpePort' + i, PORTS['physicalPorts'][device])
        }
    })

    // Populate the backup CPE port
    $('#accordionPrimary').on('change', '[id^="serviceCpePort"]', function () {
        // Matches the primary & backup CPE ports with indexes
        // Assumes they're aligned in the database
        let device = $('#deviceType').val().toLowerCase()
        let index = PORTS['physicalPorts'][device + '_primary'].indexOf(this.value)
        let port = PORTS['physicalPorts'][device + '_backup'][index]

        let suffix = this.id[this.id.length - 1]
        $(`#serviceCpePortBackup${suffix}`).val(port)
    })

    // Populate the backup CPE circuit ID
    $('#accordionPrimary').on('change', '[id^="serviceClci"]', function () {
        let suffix = this.id[this.id.length - 1]
        $(`#serviceClciBackup${suffix}`).val(this.value + ':B')
    })

    // Hide/show the bandwidth or IP SLA field if INTERNET VRF
    // TODO: add required attributes to IPSLA
    $('#accordionPrimary').on('change', '[id^="serviceType"]', function () {
        let suffix = this.id[this.id.length - 1]
        if (this.value == 'INTERNET') {
            $(`#serviceBandwidth${suffix}`).closest('.form-group').show();
            $(`#serviceBandwidthBackup${suffix}`).closest('.form-group').show();
            $(`#servicePrimaryIpsla${suffix}`).closest('.form-group').hide();
        } else {
            $(`#serviceBandwidth${suffix}`).closest('.form-group').hide();
            $(`#serviceBandwidthBackup${suffix}`).closest('.form-group').hide();
            $(`#servicePrimaryIpsla${suffix}`).closest('.form-group').show();
        }
    })

    // Populate backup IPSLA entry
    $('#accordionPrimary').on('keyup', '[id^="servicePrimaryIpsla"]', function () {
        let suffix = this.id[this.id.length - 1];
        let firstChar = parseInt(this.value[0]) + 1;
        $(`#serviceBackupIpsla${suffix}`).val(firstChar + this.value.slice(1));
    })

    // Populate Service VLANs based off first input
    $('#formContent').on('change', '[id^="serviceVlan"]', function () {
        // Determines if primary or backup service
        if (this.id[this.id.length - 1] != 1) {
            return
        }
        let service = this.id.slice(0, -1);
        let numServices = $('#numServices').val();
        let vlan = parseInt(this.value)
        for (let i = 2; i <= numServices; i++){
            $(`#${service}${i}`).val(vlan += 1).change()
        }
    })


    // Disable dropdown value of selected CPE port for other selects
    $("#accordionPrimary").on('change', "select.port-select", function() {
        $("select.port-select option[value='" + $(this).data('index') + "']").prop('disabled', false); // reset others on change everytime
        $(this).data('index', this.value);
        $("select.port-select option[value='" + this.value + "']:not([value=''])").prop('disabled', true);
        $(this).find("option[value='" + this.value + "']:not([value=''])").prop('disabled', false); // Do not apply the logic to the current one
    });

    // TODO: MSU ID manipulation for dual CPE?
    // TODO: QoL: disable port speed options if site bandwidth is above it

});



// Event Listeners //

// Generate pseudowire name

