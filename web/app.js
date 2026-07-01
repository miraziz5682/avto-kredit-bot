// Telegram Web App initialization
const tg = window.Telegram.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
}

// Global Application State
let appState = {
    carsConfig: {},
    selectedModel: null,
    selectedBank: null,
    selectedPosition: null,
    selectedPrice: 0,
    isManual: false,
    isCreditManual: false,
    downPaymentType: 'pct', // 'pct' or 'sum'
    calculationResult: null
};

// Formatter for Currency
function formatCurrency(num) {
    return new Intl.NumberFormat('uz-UZ').format(Math.round(num)) + " so'm";
}

// Formatter for raw numbers (replaces spaces)
function sanitizeInputString(str) {
    return str.replace(/\s+/g, '').replace(/,/g, '.');
}

// Progress Stepper view controller
function updateProgressTracker(currentStep) {
    for (let i = 1; i <= 4; i++) {
        const dot = document.getElementById(`dot-${i}`);
        const line = document.getElementById(`line-${i}`);
        
        if (i < currentStep) {
            dot.className = 'step-dot completed';
            dot.innerText = '✓';
            if (line) line.className = 'step-line active';
        } else if (i === currentStep) {
            dot.className = 'step-dot active';
            dot.innerText = i;
            if (line) line.className = 'step-line';
        } else {
            dot.className = 'step-dot';
            dot.innerText = i;
            if (line) line.className = 'step-line';
        }
    }
}

// Step Router
function goToStep(step) {
    // Hide all step sections
    document.querySelectorAll('.step-section').forEach(section => {
        section.classList.remove('active');
    });
    
    // Show selected step section
    const activeSection = document.getElementById(`step-${step}`);
    if (activeSection) {
        activeSection.classList.add('active');
    } else if (step === 5) {
        document.getElementById('results-section').classList.add('active');
    }
    
    // Update tracker
    if (step <= 4) {
        updateProgressTracker(step);
    }
    
    // Scroll to top of window
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Show/Hide Loading Indicator
function showLoading(show, text = 'Yuklanmoqda...') {
    const overlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    loadingText.innerText = text;
    if (show) {
        overlay.classList.add('active');
    } else {
        overlay.classList.remove('active');
    }
}

// Show Toast Alert Notification
function showToast(message) {
    const toast = document.getElementById('toast');
    toast.innerText = message;
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Set active style for toggle (down payment type)
function setDownPaymentType(type) {
    appState.downPaymentType = type;
    const pctToggle = document.getElementById('toggle-pct');
    const sumToggle = document.getElementById('toggle-sum');
    const inputDown = document.getElementById('input-down');
    
    if (type === 'pct') {
        pctToggle.classList.add('active');
        sumToggle.classList.remove('active');
        inputDown.placeholder = "Boshlang'ich foiz (masalan: 30)";
        
        // Show percent quick tags
        document.getElementById('quick-downs').innerHTML = `
            <span class="tag" data-value="25">25%</span>
            <span class="tag" data-value="30">30%</span>
            <span class="tag" data-value="40">40%</span>
            <span class="tag" data-value="50">50%</span>
        `;
    } else {
        pctToggle.classList.remove('active');
        sumToggle.classList.add('active');
        inputDown.placeholder = "Aniq summa (masalan: 50 000 000)";
        
        // Show sum quick tags
        const price = appState.selectedPrice || 200000000;
        const tag1 = Math.round(price * 0.25 / 1000000) * 1000000;
        const tag2 = Math.round(price * 0.30 / 1000000) * 1000000;
        const tag3 = Math.round(price * 0.40 / 1000000) * 1000000;
        const tag4 = Math.round(price * 0.50 / 1000000) * 1000000;
        
        document.getElementById('quick-downs').innerHTML = `
            <span class="tag" data-value="${tag1}">${(tag1/1000000).toFixed(0)} mln</span>
            <span class="tag" data-value="${tag2}">${(tag2/1000000).toFixed(0)} mln</span>
            <span class="tag" data-value="${tag3}">${(tag3/1000000).toFixed(0)} mln</span>
            <span class="tag" data-value="${tag4}">${(tag4/1000000).toFixed(0)} mln</span>
        `;
    }
    
    // Rebind newly created tags
    bindQuickTags();
}

// Fetch Configuration on Boot
async function fetchConfig() {
    showLoading(true, "Konfiguratsiyalar yuklanmoqda...");
    try {
        const response = await fetch('/api/cars-config');
        if (!response.ok) throw new Error("Yuklashda xatolik yuz berdi");
        appState.carsConfig = await response.json();
        renderModels();
    } catch (e) {
        showToast("Ma'lumotlarni yuklab bo'lmadi. Sahifani qayta yuklang.");
        console.error(e);
    } finally {
        showLoading(false);
    }
}

// Render Model list on Step 1
function renderModels() {
    const listContainer = document.getElementById('models-list');
    listContainer.innerHTML = '';
    
    Object.keys(appState.carsConfig).forEach(modelName => {
        const info = appState.carsConfig[modelName];
        let priceText = "";
        if (info.price) {
            priceText = formatCurrency(info.price);
        } else if (info.positions) {
            const prices = Object.values(info.positions);
            const minP = Math.min(...prices);
            priceText = `${(minP / 1000000).toFixed(1)} mln so'mdan`;
        }
        
        const card = document.createElement('div');
        card.className = 'menu-card';
        card.innerHTML = `
            <div class="card-icon">🚘</div>
            <div>
                <div class="card-title">${modelName}</div>
                <div class="card-info">${priceText}</div>
            </div>
        `;
        card.onclick = () => selectModel(modelName);
        listContainer.appendChild(card);
    });
}

// Action when Model is chosen
function selectModel(modelName) {
    appState.selectedModel = modelName;
    appState.isManual = false;
    
    const info = appState.carsConfig[modelName];
    
    if (info.mode === 'credit_manual') {
        appState.isCreditManual = true;
        appState.selectedBank = null;
        renderPositions();
        document.getElementById('btn-back-step3').onclick = () => goToStep(1);
        goToStep(3);
    } else {
        appState.isCreditManual = false;
        const banks = Object.keys(info.banks);
        
        if (banks.length === 1) {
            // Automatically select the only bank
            appState.selectedBank = banks[0];
            renderPositionsOrSkip();
        } else {
            // Render bank choices
            renderBanks(banks);
            goToStep(2);
        }
    }
}

// Render Bank Choices on Step 2
function renderBanks(banks) {
    const listContainer = document.getElementById('banks-list');
    listContainer.innerHTML = '';
    
    banks.forEach(bankName => {
        const card = document.createElement('div');
        card.className = 'menu-card';
        card.innerHTML = `
            <div class="card-icon">🏦</div>
            <div>
                <div class="card-title">${bankName}</div>
                <div class="card-info">Kalkulyatsiya</div>
            </div>
        `;
        card.onclick = () => selectBank(bankName);
        listContainer.appendChild(card);
    });
}

// Select Bank action
function selectBank(bankName) {
    appState.selectedBank = bankName;
    renderPositionsOrSkip();
}

// Position helper or directly proceed to inputs
function renderPositionsOrSkip() {
    const modelInfo = appState.carsConfig[appState.selectedModel];
    
    if (modelInfo.positions) {
        renderPositions();
        document.getElementById('btn-back-step3').onclick = () => {
            const banks = Object.keys(modelInfo.banks);
            if (banks.length === 1) {
                goToStep(1);
            } else {
                goToStep(2);
            }
        };
        goToStep(3);
    } else {
        // No positions (e.g. flat pricing models Captiva/Labo)
        appState.selectedPosition = null;
        appState.selectedPrice = modelInfo.price;
        setupInputsScreen();
    }
}

// Render positions on Step 3
function renderPositions() {
    const listContainer = document.getElementById('positions-list');
    listContainer.innerHTML = '';
    
    const modelInfo = appState.carsConfig[appState.selectedModel];
    
    Object.entries(modelInfo.positions).forEach(([posName, posPrice]) => {
        const row = document.createElement('div');
        row.className = 'menu-row';
        row.innerHTML = `
            <div>
                <div class="row-title">${posName}</div>
                <div class="row-desc">${appState.selectedBank || 'Kredit'}</div>
            </div>
            <div class="row-price">${formatCurrency(posPrice)}</div>
        `;
        row.onclick = () => selectPosition(posName, posPrice);
        listContainer.appendChild(row);
    });
}

// Select position action
function selectPosition(posName, posPrice) {
    appState.selectedPosition = posName;
    appState.selectedPrice = posPrice;
    setupInputsScreen();
}

// Set up Form Input Fields
function setupInputsScreen() {
    // Determine visibility of form fields
    const groupPrice = document.getElementById('group-manual-price');
    const groupRate = document.getElementById('group-rate');
    const groupTerm = document.getElementById('group-term');
    const additionalExp = document.getElementById('additional-expenses');
    
    // Clear previous inputs
    document.getElementById('input-price').value = '';
    document.getElementById('input-down').value = '';
    document.getElementById('input-rate').value = '';
    document.getElementById('input-term').value = '';
    
    // Default switch
    setDownPaymentType('pct');
    
    // Back button config on Step 4
    const btnBack = document.getElementById('btn-back-step4');
    
    if (appState.isManual) {
        groupPrice.style.display = 'block';
        groupRate.style.display = 'block';
        groupTerm.style.display = 'block';
        additionalExp.style.display = 'block';
        
        btnBack.onclick = () => goToStep(1);
    } else {
        groupPrice.style.display = 'none';
        
        if (appState.isCreditManual) {
            groupRate.style.display = 'block';
            groupTerm.style.display = 'block';
            additionalExp.style.display = 'block';
            btnBack.onclick = () => goToStep(3);
        } else {
            // bank choice (either Kapitalbank or Infinbank)
            groupRate.style.display = 'none';
            groupTerm.style.display = 'none';
            
                additionalExp.style.display = 'block';
            }
            
            const modelInfo = appState.carsConfig[appState.selectedModel];
            if (modelInfo.positions) {
                btnBack.onclick = () => goToStep(3);
            } else {
                const banks = Object.keys(modelInfo.banks);
                if (banks.length === 1) {
                    btnBack.onclick = () => goToStep(1);
                } else {
                    btnBack.onclick = () => goToStep(2);
                }
            }
        }
    }
    
    document.getElementById('step-4-title').innerText = appState.isManual ? 
        "Parametrlarni kiriting" : 
        `${appState.selectedModel} ${appState.selectedPosition || ''}`;
        
    goToStep(4);
}

// Handle Manual Flow Trigger
document.getElementById('btn-manual').onclick = () => {
    appState.isManual = true;
    appState.selectedModel = "Qo'lda kiritilgan avtomobil";
    appState.selectedPosition = null;
    appState.selectedBank = null;
    appState.selectedPrice = 0;
    setupInputsScreen();
};

// Bind Quick suggestion tags click handler
function bindQuickTags() {
    document.querySelectorAll('.tag').forEach(tag => {
        tag.onclick = function() {
            // Select only within its parent sibling tags
            const parent = this.parentElement;
            parent.querySelectorAll('.tag').forEach(t => t.classList.remove('selected'));
            this.classList.add('selected');
            
            const val = this.getAttribute('data-value');
            // Populate target input
            if (parent.id === 'quick-prices') {
                document.getElementById('input-price').value = formatRawInputText(val);
                appState.selectedPrice = parseFloat(val);
            } else if (parent.id === 'quick-downs') {
                document.getElementById('input-down').value = formatRawInputText(val);
            } else {
                const targetInput = parent.previousElementSibling;
                if (targetInput) targetInput.value = val;
            }
        };
    });
}

// Pretty formatting on type (helps visually with large sum inputs)
function formatRawInputText(val) {
    const clean = val.toString().replace(/\s+/g, '');
    if (isNaN(clean) || clean === "") return val;
    return new Intl.NumberFormat('uz-UZ').format(clean);
}

// Apply pretty formatting listeners to standard numeric fields
function applyFormatListeners() {
    const inputs = [document.getElementById('input-price'), document.getElementById('input-down')];
    inputs.forEach(input => {
        input.addEventListener('input', function() {
            const raw = sanitizeInputString(this.value);
            if (raw === "") return;
            if (!isNaN(raw)) {
                this.value = formatRawInputText(raw);
            }
        });
    });
}

// Collect form inputs and validate payload
async function submitCalculation() {
    const payload = {
        model: appState.selectedModel,
        position: appState.selectedPosition,
        bank: appState.selectedBank,
        price: appState.selectedPrice
    };
    
    if (appState.isManual) {
        const rawP = sanitizeInputString(document.getElementById('input-price').value);
        if (!rawP || isNaN(rawP)) {
            showToast("Avtomobil narxini to'g'ri kiriting!");
            return;
        }
        payload.price = parseFloat(rawP);
    }
    
    const downText = sanitizeInputString(document.getElementById('input-down').value);
    if (!downText || isNaN(downText)) {
        showToast("Boshlang'ich to'lov miqdorini kiriting!");
        return;
    }
    
    // Build combined text or percent based on input type switch
    payload.down_payment_text = appState.downPaymentType === 'pct' ? `${downText}%` : downText;
    
    if (appState.isManual || appState.isCreditManual) {
        const rawRate = document.getElementById('input-rate').value;
        const rawTerm = document.getElementById('input-term').value;
        
        if (!rawRate || isNaN(rawRate)) {
            showToast("Yillik foiz stavkasini kiriting!");
            return;
        }
        if (!rawTerm || isNaN(rawTerm)) {
            showToast("Kredit muddatini oyda kiriting!");
            return;
        }
        
        payload.annual_rate = parseFloat(rawRate);
        payload.months = parseInt(rawTerm);
    }
    
    // Add additional expenses (only if not Infinbank)
    if (appState.selectedBank !== 'Infinbank') {
        const insurance = document.getElementById('input-insurance').value;
        const commission = document.getElementById('input-commission').value;
        
        payload.insurance_percent = insurance ? parseFloat(insurance) : 0;
        payload.commission_percent = commission ? parseFloat(commission) : 0;
    } else {
        payload.insurance_percent = 0;
        payload.commission_percent = 0;
    }
    
    showLoading(true, "Hisob-kitob amalga oshirilmoqda...");
    
    try {
        const response = await fetch('/api/calculate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Hisoblashda xatolik");
        }
        
        appState.calculationResult = await response.json();
        renderResultsScreen();
    } catch (e) {
        showToast(e.message);
        console.error(e);
    } finally {
        showLoading(false);
    }
}

// Render dynamic elements inside results step
function renderResultsScreen() {
    const res = appState.calculationResult;
    
    // Set headers
    document.getElementById('result-car-title').innerText = res.model + (res.position ? ` ${res.position}` : '');
    document.getElementById('result-bank-title').innerText = (res.bank ? `${res.bank} / ` : '') + `${res.months} oy` + (res.annual_rate ? ` / ${res.annual_rate}%` : '');
    
    // Set core values
    document.getElementById('res-monthly-payment').innerText = formatCurrency(res.monthly_payment);
    document.getElementById('res-price').innerText = formatCurrency(res.price);
    document.getElementById('res-down-payment').innerText = `${formatCurrency(res.down_payment)} (${res.down_percent.toFixed(0)}%)`;
    document.getElementById('res-loan-amount').innerText = formatCurrency(res.loan_amount);
    
    // Show or hide additional expenses block based on simple/complex flow
    const insBlock = document.getElementById('res-insurance-block');
    const commBlock = document.getElementById('res-commission-block');
    const initBlock = document.getElementById('res-initial-total-block');
    const overBlock = document.getElementById('res-overpayment-block');
    
    if (res.is_simple) {
        insBlock.style.display = 'none';
        commBlock.style.display = 'none';
        initBlock.style.display = 'none';
        overBlock.style.display = 'none';
    } else {
        insBlock.style.display = 'flex';
        commBlock.style.display = 'flex';
        initBlock.style.display = 'flex';
        overBlock.style.display = res.overpayment ? 'flex' : 'none';
        
        document.getElementById('res-insurance').innerText = formatCurrency(res.insurance_total);
        document.getElementById('res-commission').innerText = formatCurrency(res.commission_total);
        document.getElementById('res-initial-total').innerText = formatCurrency(res.initial_total);
        if (res.overpayment) {
            document.getElementById('res-overpayment').innerText = formatCurrency(res.overpayment);
        }
    }
    
    document.getElementById('res-final-total').innerText = formatCurrency(res.final_total);
    
    // Close schedules blocks on navigation
    document.getElementById('schedule-table-container').style.display = 'none';
    document.getElementById('schedule-image-container').style.display = 'none';
    
    goToStep(5);
    showToast("Yakuniy hisob-kitob tayyor!");
}

// Draw dynamic schedule table on client
function toggleScheduleTable() {
    const tableContainer = document.getElementById('schedule-table-container');
    if (tableContainer.style.display === 'block') {
        tableContainer.style.display = 'none';
        return;
    }
    
    const res = appState.calculationResult;
    const tbody = document.getElementById('schedule-table-body');
    tbody.innerHTML = '';
    
    let balance = res.loan_amount;
    const monthlyRate = res.annual_rate ? (res.annual_rate / 12 / 100) : 0;
    
    for (let m = 1; m <= res.months; m++) {
        let interest = 0;
        let principal = res.monthly_payment;
        
        if (monthlyRate > 0) {
            interest = balance * monthlyRate;
            principal = res.monthly_payment - interest;
        }
        
        balance -= principal;
        if (m === res.months) {
            balance = 0; // Fix floating point division rounding
        }
        
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${m}</strong></td>
            <td>${formatCurrency(res.monthly_payment)}</td>
            <td>${formatCurrency(principal)}</td>
            <td>${formatCurrency(interest)}</td>
            <td>${formatCurrency(Math.max(balance, 0))}</td>
        `;
        tbody.appendChild(tr);
    }
    
    tableContainer.style.display = 'block';
    // Smooth scroll down to schedule
    tableContainer.scrollIntoView({ behavior: 'smooth' });
}

// Fetch dynamic PNG image from server
async function fetchScheduleImage() {
    const imgContainer = document.getElementById('schedule-image-container');
    if (imgContainer.style.display === 'block') {
        imgContainer.style.display = 'none';
        return;
    }
    
    const res = appState.calculationResult;
    showLoading(true, "Rasm shakllantirilmoqda...");
    
    try {
        const response = await fetch('/api/schedule-image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: res.model,
                position: res.position,
                price: res.price,
                loan_amount: res.loan_amount,
                annual_rate: res.annual_rate || 0,
                monthly_payment: res.monthly_payment,
                months: res.months
            })
        });
        
        if (!response.ok) throw new Error("Rasm yuklashda xatolik");
        
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        document.getElementById('schedule-img').src = url;
        
        imgContainer.style.display = 'block';
        imgContainer.scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
        showToast("Rasmli jadvalni yuklab bo'lmadi");
        console.error(e);
    } finally {
        showLoading(false);
    }
}

// Submit results directly back into Telegram Bot
async function submitToTelegram() {
    const res = appState.calculationResult;
    
    // Safely check user ID from Telegram web app SDK
    let chatId = null;
    if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) {
        chatId = tg.initDataUnsafe.user.id;
    }
    
    if (!chatId) {
        // Try getting chat_id from query params if available
        const urlParams = new URLSearchParams(window.location.search);
        chatId = urlParams.get('chat_id');
    }
    
    if (!chatId) {
        showToast("Telegram chat aniqlanmadi. Faqat Telegram ichida ishlatish mumkin.");
        return;
    }
    
    showLoading(true, "Telegramga yuborilmoqda...");
    
    try {
        const response = await fetch('/api/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chat_id: parseInt(chatId),
                calculation: res
            })
        });
        
        if (!response.ok) throw new Error("Xabar yuborishda xatolik");
        
        showToast("Natija muvaffaqiyatli Telegramga yuborildi!");
        
        // Auto-close WebApp window after short timeout
        if (tg) {
            setTimeout(() => {
                tg.close();
            }, 1000);
        }
    } catch (e) {
        showToast("Xabarni Telegramga yuborib bo'lmadi");
        console.error(e);
    } finally {
        showLoading(false);
    }
}

// Reset state and return to Step 1
function resetCalculator() {
    appState.selectedModel = null;
    appState.selectedBank = null;
    appState.selectedPosition = null;
    appState.selectedPrice = 0;
    appState.isManual = false;
    appState.isCreditManual = false;
    appState.calculationResult = null;
    
    goToStep(1);
}

// Init listeners and fetch configs on load
window.addEventListener('DOMContentLoaded', () => {
    fetchConfig();
    bindQuickTags();
    applyFormatListeners();
});
