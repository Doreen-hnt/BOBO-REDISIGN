document.addEventListener('DOMContentLoaded', () => {
    console.log('Project initialized');

    const barMenuItems = [...document.querySelectorAll('.bar-menu-items')];
    if (barMenuItems.length) {
        const desktopLayout = window.matchMedia('(min-width: 681px)');
        let layoutScheduled = false;

        const layoutMenu = container => {
            const items = [...container.children];
            if (!desktopLayout.matches) {
                container.classList.remove('is-masonry');
                container.style.removeProperty('height');
                items.forEach(item => {
                    item.style.removeProperty('position');
                    item.style.removeProperty('width');
                    item.style.removeProperty('left');
                    item.style.removeProperty('top');
                });
                return;
            }

            container.classList.add('is-masonry');
            container.style.height = 'auto';
            const styles = getComputedStyle(container);
            const padding = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
            const gap = parseFloat(styles.columnGap) || 12;
            const contentWidth = container.clientWidth - padding - gap;
            if (contentWidth <= 0) return;

            if (items.length === 1) {
                items[0].style.width = `${contentWidth + gap}px`;
                items[0].style.left = '0px';
                items[0].style.top = '0px';
                container.style.height = `${items[0].getBoundingClientRect().height}px`;
                return;
            }

            const columnWidth = contentWidth / 2;
            const columnHeights = [0, 0];
            const itemWeights = [];
            const initialColumns = [];
            items.forEach(item => {
                item.style.width = `${columnWidth}px`;
                const column = columnHeights[0] <= columnHeights[1] ? 0 : 1;
                initialColumns.push(column);
                const weight = Math.round(item.getBoundingClientRect().height) + gap;
                itemWeights.push(weight);
                columnHeights[column] += weight;
            });

            let assignments = new Map([[0, { changes: 0, left: [] }]]);
            itemWeights.forEach((weight, index) => {
                const nextAssignments = new Map();
                assignments.forEach((assignment, leftHeight) => {
                    [0, 1].forEach(column => {
                        const nextHeight = leftHeight + (column === 0 ? weight : 0);
                        const changes = assignment.changes + (column === initialColumns[index] ? 0 : 1);
                        const current = nextAssignments.get(nextHeight);
                        if (!current || changes < current.changes) {
                            nextAssignments.set(nextHeight, {
                                changes,
                                left: column === 0 ? [...assignment.left, index] : assignment.left,
                            });
                        }
                    });
                });
                assignments = nextAssignments;
            });

            const totalHeight = itemWeights.reduce((total, weight) => total + weight, 0);
            let bestAssignment;
            assignments.forEach((assignment, leftHeight) => {
                const difference = Math.abs(totalHeight - 2 * leftHeight);
                if (!bestAssignment ||
                    difference < bestAssignment.difference ||
                    (difference === bestAssignment.difference && assignment.changes < bestAssignment.assignment.changes)) {
                    bestAssignment = { assignment, difference };
                }
            });

            const leftItems = new Set(bestAssignment.assignment.left);
            const measureColumns = leftWidth => {
                const widths = [leftWidth, contentWidth - leftWidth];
                const heights = [0, 0];
                items.forEach((item, index) => {
                    const column = leftItems.has(index) ? 0 : 1;
                    item.style.width = `${widths[column]}px`;
                    heights[column] += item.getBoundingClientRect().height + gap;
                });
                return heights;
            };

            let lowerWidth = contentWidth * 0.42;
            let upperWidth = contentWidth * 0.58;
            const lowerHeights = measureColumns(lowerWidth);
            const upperHeights = measureColumns(upperWidth);
            let balancedWidth;
            if (lowerHeights[0] <= lowerHeights[1] && upperHeights[0] >= upperHeights[1]) {
                for (let attempt = 0; attempt < 14; attempt++) {
                    const middleWidth = (lowerWidth + upperWidth) / 2;
                    const heights = measureColumns(middleWidth);
                    if (heights[0] < heights[1]) {
                        lowerWidth = middleWidth;
                    } else {
                        upperWidth = middleWidth;
                    }
                }
                balancedWidth = (lowerWidth + upperWidth) / 2;
            } else {
                const lowerDifference = Math.abs(lowerHeights[0] - lowerHeights[1]);
                const upperDifference = Math.abs(upperHeights[0] - upperHeights[1]);
                balancedWidth = lowerDifference <= upperDifference
                    ? contentWidth * 0.42
                    : contentWidth * 0.58;
            }

            const balancedHeights = measureColumns(balancedWidth);
            const columnTops = [0, 0];
            items.forEach((item, index) => {
                const column = leftItems.has(index) ? 0 : 1;
                item.style.left = `${column === 0 ? 0 : balancedWidth + gap}px`;
                item.style.top = `${columnTops[column]}px`;
                columnTops[column] += item.getBoundingClientRect().height + gap;
            });
            container.style.height = `${Math.max(0, ...balancedHeights) - gap}px`;
        };

        const layoutAllMenus = () => {
            layoutScheduled = false;
            barMenuItems.forEach(layoutMenu);
        };

        const scheduleLayout = () => {
            if (layoutScheduled) return;
            layoutScheduled = true;
            requestAnimationFrame(layoutAllMenus);
        };

        barMenuItems.forEach(container => {
            const details = container.closest('details');
            if (details) details.addEventListener('toggle', scheduleLayout);
        });
        window.addEventListener('resize', scheduleLayout);
        if ('ResizeObserver' in window) {
            const menuObserver = new ResizeObserver(scheduleLayout);
            barMenuItems.forEach(container => {
                container.querySelectorAll('.bar-menu-item').forEach(item => menuObserver.observe(item));
            });
        }
        layoutAllMenus();
    }

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
