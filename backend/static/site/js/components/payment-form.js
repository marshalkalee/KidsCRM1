(function () {
    $(document).on("submit", "#js-payment-form", function (e) {
      e.preventDefault();
      const $form = $(this);
      const $button = $("#js-submit-payment");
      if ($button.prop("disabled")) return;
      $button.prop("disabled", true).text("Обработка...");
  
      $.post({
        url: `/payments/child/${$form.data("child-id")}/record/`,
        data: $form.serialize(),
      }).done(function (data) {
        window.KidsCRM.toast.success(`Оплачено ${data.paid_amount} ₸. Остаток долга: ${data.remaining_debt} ₸`);
        $("#js-current-debt").text(data.remaining_debt);
        $("#id_amount").val(data.remaining_debt);
      }).fail(function () {
        window.KidsCRM.toast.error("Не удалось принять оплату");
        $button.prop("disabled", false).text("Принять оплату");
      });
    });
  })();