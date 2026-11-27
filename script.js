document.querySelectorAll('.photo-reel').forEach(reel => {
    const track = reel.querySelector('.photo-reel-track');
    const controls = reel.querySelector('.photo-reel-controls');
    const [previous, next] = controls.querySelectorAll('button');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    function updateControls() {
        const end = track.scrollWidth - track.clientWidth;
        controls.hidden = end <= 2;
        previous.setAttribute('aria-disabled', String(track.scrollLeft <= 2));
        next.setAttribute('aria-disabled', String(track.scrollLeft >= end - 2));
    }

    [previous, next].forEach((button, index) => {
        button.addEventListener('click', () => {
            if (button.getAttribute('aria-disabled') === 'true') return;
            const [first, second] = track.children;
            const step = second.getBoundingClientRect().left - first.getBoundingClientRect().left;
            const count = Math.max(1, Math.floor(track.clientWidth / step));
            track.scrollBy({
                left: step * count * (index ? 1 : -1),
                behavior: reduceMotion.matches ? 'instant' : 'smooth',
            });
        });
    });

    track.addEventListener('scroll', updateControls, { passive: true });
    window.addEventListener('resize', updateControls);
    updateControls();
});

document.addEventListener('DOMContentLoaded', () => {
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
    const note = document.querySelector('#booking-note');
    const call = document.querySelector('.booking-call');
    const phoneFormat = /^(?:\+7|8)[ -]*(?:\([0-9]{3}\)|[0-9]{3})[ -]*[0-9]{3}[ -]*[0-9]{2}[ -]*[0-9]{2}$/;
    let attempt;

    async function fetchBooking(url, options, timeout) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const response = await fetch(url, { ...options, signal: controller.signal });
            return { ok: response.ok, data: await response.json() };
        } finally {
            clearTimeout(timer);
        }
    }

    bookingForm.addEventListener('input', () => {
        phone.setCustomValidity('');
        status.textContent = '';
    });

    bookingForm.addEventListener('submit', async event => {
        event.preventDefault();
        if (fields.disabled) return;

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
            const { ok, data: result } = await fetchBooking(bookingForm.action, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...data, requestId: attempt.id }),
            }, 10000);
            if (!ok) {
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
            const { ok, data } = await fetchBooking(`${bookingForm.action}/status`, {
                mode: 'same-origin',
                cache: 'no-store',
            }, 5000);
            if (!ok || data.bookingAvailable !== true) {
                throw new Error('Booking server unavailable');
            }
            fields.hidden = false;
            fields.disabled = false;
            note.hidden = false;
            call.hidden = true;
        } catch {
            status.textContent = 'Онлайн-бронирование пока недоступно. Забронировать столик можно по телефону.';
        }
    }

    checkBookingServer();
}
