// Frontend Helper JavaScript for TG Member Adder

document.addEventListener('DOMContentLoaded', () => {
    initTaskPolling();
});

// Modal helpers
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'flex';
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

// Toast alerts
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:10px;';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `glass-card badge-${type}`;
    toast.style.cssText = 'padding:12px 20px;border-radius:10px;font-weight:600;min-width:250px;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// Session OTP Auth Flow
let tempSessionString = '';
let tempPhoneCodeHash = '';
let currentPhone = '';

async function requestOTP() {
    const phone = document.getElementById('phone_input').value.trim();
    if (!phone) {
        showToast('Please enter a phone number', 'danger');
        return;
    }
    currentPhone = phone;
    showToast('Sending OTP request to Telegram...', 'info');
    
    try {
        const res = await fetch('/api/sessions/request_code', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({phone_number: phone})
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            tempPhoneCodeHash = data.phone_code_hash;
            tempSessionString = data.session_string;
            document.getElementById('step-1-phone').style.display = 'none';
            document.getElementById('step-2-otp').style.display = 'block';
            showToast('OTP sent to Telegram! Enter the code below.', 'success');
        } else {
            showToast(data.message || 'Failed to send OTP', 'danger');
        }
    } catch (err) {
        showToast('Server error requesting OTP', 'danger');
    }
}

async function verifyOTP() {
    const otp = document.getElementById('otp_input').value.trim();
    if (!otp) {
        showToast('Please enter the OTP code', 'danger');
        return;
    }
    showToast('Verifying code...', 'info');
    
    try {
        const res = await fetch('/api/sessions/login_code', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                phone_number: currentPhone,
                phone_code_hash: tempPhoneCodeHash,
                code: otp,
                session_string: tempSessionString
            })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('Session logged in successfully!', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.message || 'OTP verification failed', 'danger');
        }
    } catch (err) {
        showToast('Server error verifying OTP', 'danger');
    }
}

// Task creation submit
async function submitTask(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    
    const taskData = {
        name: formData.get('name'),
        source_group_link: formData.get('source_group_link'),
        target_group_link: formData.get('target_group_link'),
        user_session_id: formData.get('user_session_id'),
        max_members: formData.get('max_members'),
        delay_between_adds: formData.get('delay_between_adds'),
        filter_keywords: formData.get('filter_keywords') ? formData.get('filter_keywords').split(',').map(s => s.trim()) : [],
        exclude_keywords: formData.get('exclude_keywords') ? formData.get('exclude_keywords').split(',').map(s => s.trim()) : []
    };
    
    try {
        const res = await fetch('/api/tasks/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(taskData)
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('Task created and running!', 'success');
            closeModal('createTaskModal');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.message || 'Failed to create task', 'danger');
        }
    } catch (err) {
        showToast('Server error creating task', 'danger');
    }
}

// Live polling for task status
function initTaskPolling() {
    const runningProgressBars = document.querySelectorAll('.task-progress[data-task-id]');
    if (runningProgressBars.length === 0) return;
    
    setInterval(async () => {
        runningProgressBars.forEach(async (bar) => {
            const taskId = bar.getAttribute('data-task-id');
            try {
                const res = await fetch(`/api/tasks/${taskId}/status`);
                const data = await res.json();
                
                const fill = bar.querySelector('.progress-bar-fill');
                if (fill) fill.style.width = `${data.progress}%`;
                
                const statusBadge = document.getElementById(`task-status-${taskId}`);
                if (statusBadge) {
                    statusBadge.innerText = data.status;
                    statusBadge.className = `badge badge-${data.status === 'completed' ? 'success' : data.status === 'failed' ? 'danger' : 'info'}`;
                }
                
                if (data.status === 'completed' || data.status === 'failed') {
                    setTimeout(() => location.reload(), 2000);
                }
            } catch (err) {
                console.error(err);
            }
        });
    }, 4000);
}
