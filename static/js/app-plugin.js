// app-plugin.js — проверка плагина и автоматическая установка
(function () {
  const L = (...a)=>{ try{ console.log('[plugin]', ...a); }catch{} };
  const W = (...a)=>{ try{ console.warn('[plugin]', ...a); }catch{} };
  const E = (...a)=>{ try{ console.error('[plugin]', ...a); }catch{} };

  let pluginInstalled = false;

  async function checkPluginStatus() {
    try {
      const response = await fetch('/api/plugin-status', { cache: 'no-store' });
      const data = await response.json();
      pluginInstalled = data.installed;
      L('Plugin status:', pluginInstalled);
      return pluginInstalled;
    } catch (error) {
      E('Plugin check error:', error);
      return false;
    }
  }

  async function redirectToPluginInstall() {
    L('Redirecting to plugin install page');
    window.location.href = '/plugin-install.html';
  }

  async function installPrinter(printerData) {
    if (!pluginInstalled) {
      W('Plugin not installed, redirecting...');
      await redirectToPluginInstall();
      return;
    }

    // Показываем анимацию установки
    const progressModal = showInstallProgress(printerData);
    
    try {
      L('Installing printer via plugin:', printerData);
      
      const response = await fetch('/api/install', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(printerData)
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      L('Install result:', result);

      // Скрываем прогресс и показываем результат
      hideInstallProgress(progressModal);
      
      if (result.success) {
        showNotification('✅ Принтер успешно установлен!', 'success');
      } else {
        showNotification('❌ Ошибка установки: ' + (result.error || 'Неизвестная ошибка'), 'error');
      }
    } catch (error) {
      E('Install error:', error);
      hideInstallProgress(progressModal);
      showNotification('❌ Ошибка установки: ' + error.message, 'error');
    }
  }

  function showInstallProgress(printerData) {
    // Создаем модальное окно прогресса
    const modal = document.createElement('div');
    modal.className = 'install-progress-modal';
    modal.innerHTML = `
      <div class="install-progress-content">
        <div class="install-progress-header">
          <h3>🔄 Установка принтера</h3>
          <div class="printer-info">
            <strong>${printerData.model}</strong><br>
            <small>IP: ${printerData.ip} | Host: ${printerData.host}</small>
          </div>
        </div>
        
        <div class="install-progress-body">
          <div class="progress-steps">
            <div class="step active" data-step="1">
              <div class="step-icon">📥</div>
              <div class="step-text">Загрузка драйверов</div>
            </div>
            <div class="step" data-step="2">
              <div class="step-icon">🔧</div>
              <div class="step-text">Установка драйверов</div>
            </div>
            <div class="step" data-step="3">
              <div class="step-icon">🖨️</div>
              <div class="step-text">Настройка принтера</div>
            </div>
            <div class="step" data-step="4">
              <div class="step-icon">✅</div>
              <div class="step-text">Завершение</div>
            </div>
          </div>
          
          <div class="progress-bar">
            <div class="progress-fill"></div>
          </div>
          
          <div class="progress-text">Подготовка к установке...</div>
        </div>
      </div>
    `;
    
    // Стили для модального окна
    Object.assign(modal.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      width: '100%',
      height: '100%',
      backgroundColor: 'rgba(0, 0, 0, 0.7)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: '10000',
      opacity: '0',
      transition: 'opacity 0.3s ease'
    });
    
    // Стили для контента
    const content = modal.querySelector('.install-progress-content');
    Object.assign(content.style, {
      backgroundColor: 'white',
      borderRadius: '12px',
      padding: '2rem',
      maxWidth: '500px',
      width: '90%',
      boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
      transform: 'scale(0.9)',
      transition: 'transform 0.3s ease'
    });
    
    // Добавляем CSS стили
    const style = document.createElement('style');
    style.textContent = `
      .install-progress-modal .install-progress-header {
        text-align: center;
        margin-bottom: 2rem;
      }
      
      .install-progress-modal .install-progress-header h3 {
        margin: 0 0 1rem 0;
        color: #1f2937;
        font-size: 1.5rem;
      }
      
      .install-progress-modal .printer-info {
        background: #f3f4f6;
        padding: 1rem;
        border-radius: 8px;
        color: #6b7280;
      }
      
      .install-progress-modal .progress-steps {
        display: flex;
        justify-content: space-between;
        margin-bottom: 2rem;
        position: relative;
      }
      
      .install-progress-modal .progress-steps::before {
        content: '';
        position: absolute;
        top: 20px;
        left: 20px;
        right: 20px;
        height: 2px;
        background: #e5e7eb;
        z-index: 1;
      }
      
      .install-progress-modal .step {
        display: flex;
        flex-direction: column;
        align-items: center;
        position: relative;
        z-index: 2;
        opacity: 0.5;
        transition: all 0.3s ease;
      }
      
      .install-progress-modal .step.active {
        opacity: 1;
      }
      
      .install-progress-modal .step.completed {
        opacity: 1;
      }
      
      .install-progress-modal .step-icon {
        width: 40px;
        height: 40px;
        background: #e5e7eb;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.2rem;
        margin-bottom: 0.5rem;
        transition: all 0.3s ease;
      }
      
      .install-progress-modal .step.active .step-icon {
        background: #3b82f6;
        color: white;
        animation: pulse 2s infinite;
      }
      
      .install-progress-modal .step.completed .step-icon {
        background: #10b981;
        color: white;
      }
      
      .install-progress-modal .step-text {
        font-size: 0.875rem;
        color: #6b7280;
        text-align: center;
        max-width: 80px;
      }
      
      .install-progress-modal .progress-bar {
        width: 100%;
        height: 8px;
        background: #e5e7eb;
        border-radius: 4px;
        overflow: hidden;
        margin-bottom: 1rem;
      }
      
      .install-progress-modal .progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #3b82f6, #10b981);
        width: 0%;
        transition: width 0.5s ease;
        border-radius: 4px;
      }
      
      .install-progress-modal .progress-text {
        text-align: center;
        color: #6b7280;
        font-size: 0.875rem;
      }
      
      @keyframes pulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.1); }
      }
    `;
    
    document.head.appendChild(style);
    document.body.appendChild(modal);
    
    // Анимация появления
    setTimeout(() => {
      modal.style.opacity = '1';
      content.style.transform = 'scale(1)';
    }, 100);
    
    // Симуляция прогресса
    simulateProgress(modal, printerData);
    
    return modal;
  }
  
  function simulateProgress(modal, printerData) {
    const steps = modal.querySelectorAll('.step');
    const progressFill = modal.querySelector('.progress-fill');
    const progressText = modal.querySelector('.progress-text');
    
    const stepTexts = [
      'Загрузка драйверов с сервера...',
      'Установка драйверов принтера...',
      'Настройка порта и очереди печати...',
      'Завершение установки...'
    ];
    
    let currentStep = 0;
    
    function nextStep() {
      if (currentStep < steps.length) {
        // Помечаем предыдущий шаг как завершенный
        if (currentStep > 0) {
          steps[currentStep - 1].classList.remove('active');
          steps[currentStep - 1].classList.add('completed');
        }
        
        // Активируем текущий шаг
        if (currentStep < steps.length) {
          steps[currentStep].classList.add('active');
          progressText.textContent = stepTexts[currentStep];
          progressFill.style.width = `${((currentStep + 1) / steps.length) * 100}%`;
        }
        
        currentStep++;
        
        // Продолжаем через случайный интервал (2-4 секунды)
        if (currentStep < steps.length) {
          setTimeout(nextStep, 2000 + Math.random() * 2000);
        }
      }
    }
    
    // Запускаем первый шаг
    setTimeout(nextStep, 500);
  }
  
  function hideInstallProgress(modal) {
    if (!modal) return;
    
    const content = modal.querySelector('.install-progress-content');
    
    // Анимация исчезновения
    modal.style.opacity = '0';
    content.style.transform = 'scale(0.9)';
    
    setTimeout(() => {
      if (modal.parentNode) {
        modal.parentNode.removeChild(modal);
      }
    }, 300);
  }

  function showNotification(message, type = 'info') {
    // Создаем уведомление
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // Стили для уведомления
    Object.assign(notification.style, {
      position: 'fixed',
      top: '20px',
      right: '20px',
      padding: '1rem 1.5rem',
      borderRadius: '8px',
      color: 'white',
      fontWeight: '500',
      zIndex: '10000',
      maxWidth: '400px',
      boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
      transform: 'translateX(100%)',
      transition: 'transform 0.3s ease'
    });

    // Цвета в зависимости от типа
    const colors = {
      success: '#10b981',
      error: '#ef4444',
      info: '#3b82f6'
    };
    notification.style.backgroundColor = colors[type] || colors.info;

    document.body.appendChild(notification);

    // Анимация появления
    setTimeout(() => {
      notification.style.transform = 'translateX(0)';
    }, 100);

    // Автоматическое скрытие через 5 секунд
    setTimeout(() => {
      notification.style.transform = 'translateX(100%)';
      setTimeout(() => {
        if (notification.parentNode) {
          notification.parentNode.removeChild(notification);
        }
      }, 300);
    }, 5000);
  }

  // Перехватываем клики по кнопкам установки
  function interceptInstallClicks() {
    document.addEventListener('click', async (e) => {
      const btn = e.target.closest('a.btn.install, .btn.install, [data-action="install"], .btn-install');
      if (!btn) return;

      e.preventDefault();
      e.stopPropagation();

      // Получаем данные принтера из строки
      const row = btn.closest('.row');
      if (!row) {
        showNotification('❌ Не удалось найти данные принтера', 'error');
        return;
      }

      // Получаем чекбоксы
      const cbPrn = row.querySelector('input.cb-prn');
      const cbScn = row.querySelector('input.cb-scn');
      
      if (!cbPrn && !cbScn) {
        showNotification('❌ Не найдены чекбоксы выбора компонентов', 'error');
        return;
      }

      const printerChecked = cbPrn ? cbPrn.checked : false;
      const scannerChecked = cbScn ? cbScn.checked : false;

      if (!printerChecked && !scannerChecked) {
        showNotification('❌ Выберите хотя бы один компонент: принтер и/или сканер', 'error');
        return;
      }

      // Получаем данные принтера
      const ip = btn.dataset.ip || '';
      const host = btn.dataset.host || '';
      const model = btn.dataset.model || '';
      const desc = btn.dataset.desc || '';

      if (!ip || !model) {
        showNotification('❌ Неполные данные принтера', 'error');
        return;
      }

      // Определяем вариант установки
      let variant = null;
      if (printerChecked && scannerChecked) variant = 'all';
      else if (printerChecked) variant = 'printer';
      else if (scannerChecked) variant = 'scanner';

      const printerData = {
        ip: ip,
        host: host,
        model: model,
        desc: desc,
        variant: variant,
        printer: printerChecked,
        scanner: scannerChecked
      };

      showNotification('🔄 Начинаем установку...', 'info');
      await installPrinter(printerData);
    });
  }

  // Инициализация
  async function init() {
    L('Initializing plugin system');
    
    // Проверяем статус плагина при загрузке
    const installed = await checkPluginStatus();
    
    if (!installed) {
      L('Plugin not installed, redirecting to install page');
      await redirectToPluginInstall();
      return;
    }

    // Если плагин установлен, перехватываем клики
    interceptInstallClicks();
    L('Plugin system initialized');
  }

  // Запускаем инициализацию
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Экспортируем функции для использования в других скриптах
  window.PluginSystem = {
    checkStatus: checkPluginStatus,
    installPrinter: installPrinter,
    showNotification: showNotification
  };

})();
