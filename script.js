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

    bookingForm.addEventListener('input', () => {
        phone.setCustomValidity('');
        status.textContent = '';
    });

    bookingForm.addEventListener('submit', event => {
        event.preventDefault();

        const phoneFormat = /^(?:\+7|8)[ -]*(?:\([0-9]{3}\)|[0-9]{3})[ -]*[0-9]{3}[ -]*[0-9]{2}[ -]*[0-9]{2}$/;
        if (!phoneFormat.test(phone.value.trim())) {
            phone.setCustomValidity('Введите номер в формате +7 (___) ___-__-__ или 8 ___ ___-__-__.');
            phone.reportValidity();
            return;
        }

        status.textContent = 'Проверка пройдена. Тестовая заявка не отправлена.';
    });

    bookingForm.querySelector('fieldset').disabled = false;
}
