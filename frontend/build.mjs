import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
mkdirSync('../backend/static/vendor', { recursive: true });
copyFileSync('node_modules/htmx.org/dist/htmx.min.js', '../backend/static/vendor/htmx.min.js');
const chart = readFileSync('node_modules/chart.js/dist/chart.umd.js', 'utf8');
writeFileSync('../backend/static/vendor/chart.umd.js', chart.replace(/^\/\/# sourceMappingURL=.*$/gm, ''));
copyFileSync('node_modules/htmx.org/LICENSE', '../backend/static/vendor/HTMX-LICENSE.txt');
copyFileSync('node_modules/chart.js/LICENSE.md', '../backend/static/vendor/CHARTJS-LICENSE.txt');
