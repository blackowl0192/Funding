function formatNumber(value, suffix = "") {
  if (!Number.isFinite(value)) {
    return `-${suffix}`;
  }
  const fixed = value.toFixed(8).replace(/\.?0+$/, "");
  return `${fixed}${suffix}`;
}

function initUploadDropZone() {
  const dropZone = document.querySelector(".drop-zone");
  const input = document.querySelector("#file-input");
  if (!dropZone || !input) {
    return;
  }

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (event) => {
    const files = event.dataTransfer?.files;
    if (files && files.length > 0) {
      input.files = files;
    }
  });
}

function initSettingsPreview() {
  const form = document.querySelector("[data-settings-form]");
  if (!form) {
    return;
  }

  const readNumber = (name) => Number(form.elements[name]?.value || 0);
  const write = (key, value, suffix = "") => {
    const target = form.querySelector(`[data-derived="${key}"]`);
    if (target) {
      target.textContent = formatNumber(value, suffix);
    }
  };

  const update = () => {
    const total = readNumber("total_capital");
    const spotBudget = readNumber("spot_budget");
    const futuresMarginBudget = readNumber("futures_margin_budget");
    const leverage = Number(form.elements.futures_leverage?.value || 1);
    const discountRate = readNumber("fee_discount") / 100;
    const feeMultiplier = 1 - discountRate;

    const futuresCapacity = futuresMarginBudget * leverage;
    write("free_reserve", total - spotBudget - futuresMarginBudget);
    write("max_futures_notional", futuresCapacity);
    write("max_hedged_notional", Math.min(spotBudget, futuresCapacity));
    write(
      "capital_utilization_ratio",
      total > 0 ? ((spotBudget + futuresMarginBudget) / total) * 100 : 0,
      "%"
    );
    write(
      "effective_spot_maker_fee",
      readNumber("spot_maker_base_fee") * feeMultiplier,
      "%"
    );
    write(
      "effective_spot_taker_fee",
      readNumber("spot_taker_base_fee") * feeMultiplier,
      "%"
    );
    write(
      "effective_futures_maker_fee",
      readNumber("futures_maker_base_fee") * feeMultiplier,
      "%"
    );
    write(
      "effective_futures_taker_fee",
      readNumber("futures_taker_base_fee") * feeMultiplier,
      "%"
    );
  };

  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();
}

function initPageEnhancements() {
  initUploadDropZone();
  initSettingsPreview();
}

document.addEventListener("DOMContentLoaded", initPageEnhancements);
document.body.addEventListener("htmx:afterSwap", initPageEnhancements);
