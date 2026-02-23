let socket, currentChatId = null, currentPartnerId = null;

async function init() {
    socket = io();

    socket.on('new_message', (msg) => {
        if (msg.chat_id === currentChatId) {
            renderNewMessage(msg);
        }
        loadChats();
    });

    renderApp();
}

function getAvatar(name, avatar) {
    if (avatar && avatar !== '/static/default_avatar.png') return avatar;
    return `https://ui-avatars.com/api/?name=${encodeURIComponent(name)}&background=10b981&color=fff&size=128&bold=true`;
}

function cleanUsername(username) {
    return (username || '').replace(/^@+/, '');
}

// ====================== ИСПРАВЛЕННЫЙ РЕНДЕР (safe-area для iPhone) ======================
function renderApp() {
    document.getElementById('root').innerHTML = `
        <div class="h-screen w-screen overflow-hidden bg-zinc-950 flex">

            <!-- СПИСОК ЧАТОВ -->
            <div id="sidebar" class="w-full md:w-96 bg-zinc-950 border-r border-zinc-800 flex flex-col">
                <div class="h-14 bg-zinc-900 border-b flex items-center px-4">
                    <h1 class="text-2xl font-semibold text-white">Чаты</h1>
                    <div class="flex-1"></div>
                    <button class="text-2xl mr-4">📷</button>
                    <button onclick="newChat()" class="text-3xl text-emerald-400">✚</button>
                </div>
                <div id="chat-list" class="flex-1 overflow-auto"></div>
            </div>

            <!-- ЧАТ -->
            <div id="chat-area" class="flex-1 flex flex-col hidden md:flex bg-zinc-950">
                <div id="chat-header" class="h-14 bg-zinc-900 border-b px-4 flex items-center"></div>
                
                <!-- Сообщения с большим отступом снизу -->
                <div id="messages" class="flex-1 overflow-auto p-6 space-y-6 bg-zinc-950 pb-40 md:pb-6"></div>
                
                <!-- Панель ввода — исправлена для iPhone (не перекрывается) -->
                <div class="bg-zinc-900 border-t border-zinc-700 px-4 py-3 pb-[max(20px,env(safe-area-inset-bottom))] md:pb-4 flex gap-3">
                    <button onclick="attachFile()" class="text-3xl text-zinc-400 px-3">📎</button>
                    <button onclick="startVoiceRecording()" class="text-3xl text-zinc-400 px-3">🎤</button>
                    <input id="msg-input" 
                           class="flex-1 bg-zinc-800 rounded-3xl px-6 py-3.5 outline-none text-base" 
                           placeholder="Сообщение..." 
                           onkeypress="if(event.key==='Enter') sendMessage()">
                    <button onclick="sendMessage()" 
                            class="bg-emerald-600 w-12 h-12 rounded-3xl flex items-center justify-center text-2xl shadow-lg active:scale-95">➤</button>
                </div>
            </div>
        </div>

        <!-- Нижняя панель для телефона -->
        <div id="mobile-bottom-nav" class="fixed bottom-0 left-0 right-0 bg-zinc-900 border-t border-zinc-700 md:hidden z-50 pb-[env(safe-area-inset-bottom)]">
            <div class="flex justify-around py-2 text-xs">
                <div onclick="showChatsMobile()" class="flex flex-col items-center text-emerald-500">
                    <span class="text-3xl">💬</span>
                    <span class="mt-1">Чаты</span>
                </div>
                <div onclick="showNotifications()" class="flex flex-col items-center text-zinc-400">
                    <span class="text-3xl">🔔</span>
                    <span class="mt-1">Уведомления</span>
                </div>
                <div onclick="showMoreMenu()" class="flex flex-col items-center text-zinc-400">
                    <span class="text-3xl">⚙️</span>
                    <span class="mt-1">Настройки</span>
                </div>
            </div>
        </div>
    `;

    loadChats();
}

// ====================== Остальные функции ======================
async function loadChats() {
    const res = await fetch('/api/chats');
    const chats = await res.json();
    let html = '';

    chats.forEach(c => {
        const avatar = getAvatar(c.name, c.avatar);
        const isActive = (c.id === currentPartnerId) ? 'bg-zinc-800' : 'hover:bg-zinc-800';
        const unread = c.unread > 0 ?
            `<div class="bg-emerald-500 text-white text-xs font-bold min-w-[22px] h-5 flex items-center justify-center rounded-full px-1.5">${c.unread}</div>` : '';

        html += `
            <div onclick="openChat(${c.id}, '${c.name}')" class="flex items-center gap-4 px-4 py-4 cursor-pointer border-b border-zinc-800 transition-all ${isActive}">
                <div class="relative flex-shrink-0">
                    <img src="${avatar}" class="w-14 h-14 rounded-full object-cover">
                    ${c.online ? `<div class="absolute bottom-0 right-0 w-4 h-4 bg-emerald-500 border-2 border-zinc-900 rounded-full"></div>` : ''}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex justify-between">
                        <p class="font-semibold text-white truncate">${c.name}</p>
                        <p class="text-xs text-zinc-500">${c.last_time || ''}</p>
                    </div>
                    <p class="text-sm text-zinc-400 truncate">${c.last_message || 'Нет сообщений'}</p>
                </div>
                ${unread}
            </div>
        `;
    });

    document.getElementById('chat-list').innerHTML = html || `
        <div class="flex flex-col items-center justify-center h-full text-zinc-500 pt-20">
            <div class="text-7xl mb-6 opacity-50">💬</div>
            <p class="text-xl">Пока нет чатов</p>
        </div>
    `;
}

async function openChat(partnerId, name) {
    currentPartnerId = partnerId;
    await loadChats();

    const res = await fetch(`/api/chat/${partnerId}`);
    const data = await res.json();

    currentChatId = data.chat_id;
    socket.emit('join_chat', {room: data.room_key});

    const chatArea = document.getElementById('chat-area');
    const sidebar = document.getElementById('sidebar');
    const bottomNav = document.getElementById('mobile-bottom-nav');

    chatArea.classList.remove('hidden');
    if (window.innerWidth < 768) {
        sidebar.classList.add('hidden');
        bottomNav.classList.add('hidden');
    }

    const avatarUrl = data.partner_avatar || '';

    document.getElementById('chat-header').innerHTML = `
        <div class="flex items-center gap-3 w-full">
            ${window.innerWidth < 768 ? `<button onclick="backToList()" class="text-3xl pr-4">←</button>` : ''}
            <img src="${getAvatar(name, avatarUrl)}" class="w-10 h-10 rounded-full object-cover">
            <div>
                <p class="font-semibold">${name}</p>
                <p class="text-xs text-emerald-400">онлайн</p>
            </div>
        </div>
    `;

    renderMessages(data.messages);
}

function sendMessage() {
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text || !currentPartnerId) return;

    const optimisticMsg = {
        chat_id: currentChatId,
        sender_id: window.currentUser.id,
        content: text,
        timestamp: new Date().toISOString()
    };

    renderNewMessage(optimisticMsg);

    socket.emit('send_message', { partner_id: currentPartnerId, content: text });
    input.value = '';
}

function renderMessages(messages) {
    const container = document.getElementById('messages');
    let html = '';
    messages.forEach(m => {
        const time = new Date(m.timestamp).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        html += `
            <div class="flex ${m.sender_id == window.currentUser.id ? 'justify-end' : 'justify-start'}">
                <div class="max-w-[75%] px-5 py-3 rounded-3xl ${m.sender_id == window.currentUser.id ? 'bg-emerald-600 text-white' : 'bg-zinc-800'}">
                    <p>${m.content}</p>
                    <p class="text-[10px] text-right mt-1 opacity-70">${time}</p>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
    container.scrollTop = container.scrollHeight;
}

function renderNewMessage(msg) {
    if (msg.chat_id !== currentChatId) return;
    const container = document.getElementById('messages');
    const time = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });

    const div = document.createElement('div');
    div.className = `flex ${msg.sender_id == window.currentUser.id ? 'justify-end' : 'justify-start'}`;
    div.innerHTML = `
        <div class="max-w-[75%] px-5 py-3 rounded-3xl ${msg.sender_id == window.currentUser.id ? 'bg-emerald-600 text-white' : 'bg-zinc-800'}">
            <p>${msg.content}</p>
            <p class="text-[10px] text-right mt-1 opacity-70">${time}</p>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function showToast(text, isError = false) {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-6 left-1/2 -translate-x-1/2 px-6 py-3 rounded-2xl text-white text-sm shadow-2xl z-50 ${isError ? 'bg-red-600' : 'bg-emerald-600'}`;
    toast.textContent = text;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function backToList() {
    document.getElementById('chat-area').classList.add('hidden');
    document.getElementById('sidebar').classList.remove('hidden');
    document.getElementById('mobile-bottom-nav').classList.remove('hidden');
    currentPartnerId = null;
    loadChats();
}

function showChatsMobile() {
    document.getElementById('sidebar').classList.remove('hidden');
    document.getElementById('chat-area').classList.add('hidden');
    document.getElementById('mobile-bottom-nav').classList.remove('hidden');
}

function showNotifications() {
    showToast('Уведомления скоро появятся ✨', false);
}

function showMoreMenu() {
    window.location.href = '/profile';
}

function newChat() {
    showToast('Поиск друзей в верхней строке поиска', false);
}

window.onload = init;