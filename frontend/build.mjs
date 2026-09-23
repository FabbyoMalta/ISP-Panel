import { copyFileSync, mkdirSync } from 'node:fs';
mkdirSync('../backend/static/vendor', { recursive: true });
copyFileSync('node_modules/htmx.org/dist/htmx.min.js', '../backend/static/vendor/htmx.min.js');
copyFileSync('node_modules/chart.js/dist/chart.umd.js', '../backend/static/vendor/chart.umd.js');
