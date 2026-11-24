document.addEventListener('DOMContentLoaded', () => {
    console.log('Project initialized');

    const revealElements = document.querySelectorAll('.reveal');
    const prefersReducedMotion = window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (prefersReducedMotion || !('IntersectionObserver' in window)) {
        revealElements.forEach(element => element.classList.add('is-visible'));
        return;
    }

    document.documentElement.classList.add('motion-ready');

    const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.12 });

    revealElements.forEach(element => revealObserver.observe(element));
});

const bookingForm = document.querySelector('#booking-form');

if (bookingForm) {
    const date = bookingForm.elements.namedItem('date');
    const phone = bookingForm.elements.namedItem('phone');
    const status = bookingForm.querySelector('.booking-status');
    const podolskDate = new Intl.DateTimeFormat('sv-SE', {
        timeZone: 'Europe/Moscow',
        dateStyle: 'short',
    });

    date.min = podolskDate.format(new Date());

    const fields = bookingForm.querySelector('fieldset');
    let attempt;

    bookingForm.addEventListener('input', () => {
        phone.setCustomValidity('');
        status.textContent = '';
    });

    bookingForm.addEventListener('submit', async event => {
        event.preventDefault();

        const phoneFormat = /^(?:\+7|8)[ -]*(?:\([0-9]{3}\)|[0-9]{3})[ -]*[0-9]{3}[ -]*[0-9]{2}[ -]*[0-9]{2}$/;
        if (!phoneFormat.test(phone.value.trim())) {
            phone.setCustomValidity('Введите номер в формате +7 (___) ___-__-__ или 8 ___ ___-__-__.');
            phone.reportValidity();
            return;
        }

        const data = Object.fromEntries(new FormData(bookingForm));
        data.guests = Number(data.guests);
        const snapshot = JSON.stringify(data);
        if (attempt?.snapshot !== snapshot) {
            attempt = { snapshot, id: crypto.randomUUID() };
        }

        fields.disabled = true;
        status.textContent = 'Сохраняем тестовую заявку…';

        try {
            const response = await fetch(bookingForm.action, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...data, requestId: attempt.id }),
                signal: AbortSignal.timeout(10000),
            });
            const result = await response.json();
            if (!response.ok) {
                status.textContent = result.error || 'Не удалось сохранить заявку.';
                return;
            }
            if (!Number.isSafeInteger(result.id)) {
                throw new Error('Missing booking ID');
            }

            bookingForm.reset();
            attempt = undefined;
            status.textContent = `Тестовая заявка №${result.id} сохранена.`;
        } catch {
            status.textContent = 'Не удалось получить ответ сервера. Попробуйте ещё раз.';
        } finally {
            fields.disabled = false;
        }
    });

    async function checkBookingServer() {
        try {
            if (typeof crypto.randomUUID !== 'function') {
                throw new Error('Secure context required');
            }
            const response = await fetch('/api/bookings/status', {
                mode: 'same-origin',
                cache: 'no-store',
                signal: AbortSignal.timeout(5000),
            });
            if (!response.ok || (await response.json()).bookingAvailable !== true) {
                throw new Error('Booking server unavailable');
            }
            fields.disabled = false;
        } catch {
            status.textContent = 'Форма пока недоступна. Откройте сайт через сервер bo-bo.';
        }
    }

    checkBookingServer();
}
