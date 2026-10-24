/**
 * Movie Magic — Interactive Cinematic Seat Map Controller
 */

document.addEventListener("DOMContentLoaded", function () {
  const seatButtons = document.querySelectorAll(".seat:not(.seat-booked)");
  const selectedSeatsInput = document.getElementById("selected_seats");
  const selectedSeatsDisplay = document.getElementById("selected-seats-display");
  const selectedCountDisplay = document.getElementById("selected-count-display");
  const totalPriceDisplay = document.getElementById("total-price-display");
  const checkoutBtn = document.getElementById("btn-checkout");

  let selectedSeats = [];

  seatButtons.forEach((seat) => {
    seat.addEventListener("click", function () {
      const seatId = this.getAttribute("data-seat-id");
      const seatPrice = parseFloat(this.getAttribute("data-price") || 160.0);

      const index = selectedSeats.findIndex((s) => s.id === seatId);

      if (index > -1) {
        // Deselect
        selectedSeats.splice(index, 1);
        this.classList.remove("seat-selected");
        this.setAttribute("aria-checked", "false");
      } else {
        // Max 8 tickets per booking for demo sanity
        if (selectedSeats.length >= 8) {
          alert("Maximum 8 seats can be reserved per transaction in this demo.");
          return;
        }
        selectedSeats.push({ id: seatId, price: seatPrice });
        this.classList.add("seat-selected");
        this.setAttribute("aria-checked", "true");
      }

      updateSummary();
    });
  });

  function updateSummary() {
    const seatCodes = selectedSeats.map((s) => s.id);
    const total = selectedSeats.reduce((sum, s) => sum + s.price, 0.0);

    if (selectedSeatsInput) {
      selectedSeatsInput.value = JSON.stringify(seatCodes);
    }

    if (selectedSeatsDisplay) {
      selectedSeatsDisplay.textContent =
        seatCodes.length > 0 ? seatCodes.join(", ") : "None";
    }

    if (selectedCountDisplay) {
      selectedCountDisplay.textContent = selectedSeats.length;
    }

    if (totalPriceDisplay) {
      totalPriceDisplay.textContent = "₹" + total.toFixed(2);
    }

    if (checkoutBtn) {
      checkoutBtn.disabled = selectedSeats.length === 0;
    }
  }
});
