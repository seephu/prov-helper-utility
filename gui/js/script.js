(function ($) {
  /* 
  ----------------------------
  UI Functions
  ----------------------------
  */
  "use strict"; // Start of use strict

  // Toggle the side navigation
  $("#sidebarToggle, #sidebarToggleTop").on('click', function (e) {
    $("body").toggleClass("sidebar-toggled");
    $(".sidebar").toggleClass("toggled");
    if ($(".sidebar").hasClass("toggled")) {
      $('.sidebar .collapse').collapse('hide');
    };
  });

  // Close any open menu accordions when window is resized below 768px
  $(window).resize(function () {
    if ($(window).width() < 768) {
      $('.sidebar .collapse').collapse('hide');
    };

    // Toggle the side navigation when window is resized below 480px
    if ($(window).width() < 480 && !$(".sidebar").hasClass("toggled")) {
      $("body").addClass("sidebar-toggled");
      $(".sidebar").addClass("toggled");
      $('.sidebar .collapse').collapse('hide');
    };
  });

  // Prevent the content wrapper from scrolling when the fixed side navigation hovered over
  $('body.fixed-nav .sidebar').on('mousewheel DOMMouseScroll wheel', function (e) {
    if ($(window).width() > 768) {
      var e0 = e.originalEvent,
        delta = e0.wheelDelta || -e0.detail;
      this.scrollTop += (delta < 0 ? 1 : -1) * 30;
      e.preventDefault();
    }
  });

  // Scroll to top button appear
  $(document).on('scroll', function () {
    var scrollDistance = $(this).scrollTop();
    if (scrollDistance > 100) {
      $('.scroll-to-top').fadeIn();
    } else {
      $('.scroll-to-top').fadeOut();
    }
  });

  // Smooth scrolling using jQuery easing
  $(document).on('click', 'a.scroll-to-top', function (e) {
    var $anchor = $(this);
    $('html, body').stop().animate({
      scrollTop: ($($anchor.attr('href')).offset().top)
    }, 1000, 'easeInOutExpo');
    e.preventDefault();
  });



  /* 
  ----------------------------
  Utility functions
  ----------------------------
  */


  /**
 * Validates a field and toggles an error message if it does not meet the given condition.
 *
 * @param {HTMLElement} element - The input element to validate.
 * @param {string} errorMessage - The error message to display if the validation fails.
 * @param {boolean} conditional - The result of a conditional. If false the error message will be highlighted red and an error message appended.
 */
  function validateField(element, errorMessage, conditional){
    // Determine the position of the error message (input group needs to have it appended outside the group)
    let row = $(element).closest('.input-group');
    if (row.length < 1){
      row = element
    }
    let error = `<span class="error-inline">${errorMessage}</span>`;
    $(row).next('.error-inline').remove();
  
    if (conditional) {
      $(element).removeClass('border-danger');
    } else {
      $(error).insertAfter(row);
      $(element).addClass('border-danger');
    }
  }

  // Block SSH pages if no valid credentials
  function checkSshCredentials() {
    try {
      if (sshRequired) {
        if (!credentials['valid']) {
          $(':submit').prop('disabled', true)
          $('#credentialsWarning').show()
        }
      }
    }
    catch (err) { }
  }

  // Toggle opacity overlay and disables click events
  function toggleLoading() {
    $('.container').toggleClass('loading')
    $('.spinner-border').toggle()
    $('.fa-download').toggle()
  }

  // Toggle successful alert
  function toggleSuccessAlert() {
    $('.alert-danger').hide()
    $('.alert-success').show()
  }

  // Toggle error alert
  function toggleErrorAlert() {
    $('.alert-danger').show()
    $('.alert-success').hide()
  }

  // Toggles page opacity for long back-end processing times
  $('#formLoad').on('submit', async function (event) {
    event.preventDefault();
    toggleLoading();

    try {
      const formData = new FormData(event.target)
      const response = await fetch('/generate/decom', {
        method: 'POST',
        body: formData
      });

      if (response.ok) {
        // Get file information and dynmamically create URL
        const fileBlob = await response.blob();
        const fileURL = URL.createObjectURL(fileBlob);

        // Mimic a downlink link click because default form behavior is disabled
        const downloadLink = document.createElement('a');
        downloadLink.href = fileURL
        downloadLink.download = response.headers.get('fname')
        downloadLink.click()
        URL.revokeObjectURL(fileURL)
        toggleSuccessAlert()
      } else {
        toggleErrorAlert()
      }
    } catch (error) {
      console.error('Error', error);
    } finally {
      toggleLoading();
    }
  })

  // Verify SSH credentials on pages where required
  checkSshCredentials()

  // Updates percentage of form progress bar based off required input fields
  $('form').on('input change', function(){
    const requiredFields = $('input[required], select[required]');
    const progressBar = $('.progress-bar');

    // Check if required inputs are empty
    var totalFields = requiredFields.length;
    var filledFields = requiredFields.filter(function(){
      return $(this).val() !== '';
    }).length;

    // Calculate progress % and update
    var progress = (filledFields / totalFields) * 100;
    progressBar.css('width', progress + '%');
    if (progress == 100) {
      progressBar.addClass('bg-success')
    } else {
      progressBar.removeClass('bg-success')
    }
  });

  // Highlight text fields when filled out
  $('body').on('change', ':input.form-control', function () {
    $.trim(this.value) !== '' ? $(this).addClass('border-success') : $(this).removeClass('border-success')
  })


  // Validate IP address fields
  $('form').on('change', '[data-validate="ip"]', function () {
    let valid = /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/
    let error = 'Invalid IP address';
    validateField(this, error, $.trim(this.value).match(valid))
  })

  // Validate VLAN fields - need to refactor into function (including IP addr validate)
  $('form').on('change', '[data-validate="vlan"]', function(){
    let vlan = Number(this.value);
    let error = 'Invalid VLAN range (1-4094)';
    validateField(this, error, vlan < 4094 && vlan)
  })

  // Populate filename for custom-file-input
  $(".custom-file-input").on("change", function () {
    var fileName = $(this).val().split("\\").pop();
    $(this).siblings(".custom-file-label").addClass("selected").html(fileName);
  });

})(jQuery); // End of use strict
