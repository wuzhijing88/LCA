"use strict";

const sponsorForm = document.getElementById("sponsor-form");
const amountInput = document.getElementById("amount");
const amountChoices = Array.from(sponsorForm.querySelectorAll("[data-amount]"));

function updateAmountChoice() {
  for (const choice of amountChoices) {
    choice.setAttribute("aria-pressed", String(amountInput.value !== "" && Number(amountInput.value) === Number(choice.dataset.amount)));
  }
}

// 页面级事件委托随页面文档一起释放，不创建计时器或后台任务。
sponsorForm.addEventListener("click", (event) => {
  const choice = event.target.closest("[data-amount]");
  if (choice === null) return;
  amountInput.value = choice.dataset.amount;
  updateAmountChoice();
});
amountInput.addEventListener("input", updateAmountChoice);
updateAmountChoice();
