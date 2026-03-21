// Global app script for evicted_frontend (optional enhancements)
document.addEventListener('DOMContentLoaded', function() {
    // Sync lot_display to lot_number hidden field if present
    var lotDisplay = document.getElementById('lot_display');
    var lotHidden = document.getElementById('lot_number');
    if (lotDisplay && lotHidden && lotDisplay.dataset.syncTo === 'lot_number') {
        lotDisplay.addEventListener('input', function() {
            lotHidden.value = lotDisplay.value;
        });
    }
});
