# Render the architecture diagram

`architecture.drawio` contains both the editable layout and an embedded Mermaid definition. Keep their labels and connections consistent when editing. Render the drawio layout to preserve the established geometry, colors, and edge routing.

The export below uses draw.io's renderer in a separate headless Chrome process. It does not use the team's authenticated browser. Requirements are Git, Node.js, npm, and Google Chrome at `/usr/bin/google-chrome`.

1. Check that `/tmp/opencode` exists. Install the temporary renderer at the pinned source revision:

	```sh
	git clone --filter=blob:none --no-checkout https://github.com/jgraph/drawio.git /tmp/opencode/cpr-diagram-render
	git -C /tmp/opencode/cpr-diagram-render sparse-checkout init --cone
	git -C /tmp/opencode/cpr-diagram-render sparse-checkout set src/main/webapp
	git -C /tmp/opencode/cpr-diagram-render checkout 96f8c7acb719aa93f0108eecedf20c3afdcbe431
	npm install --prefix /tmp/opencode/cpr-diagram-render --no-save --package-lock=false puppeteer-core@24.25.0
	```

2. From the CPR root, run this export. It reads the XML, blocks network requests, and writes `docs/architecture.jpg` at scale 1 with a 10-pixel border and JPEG quality 95:

	```sh
	node <<'JS'
	const fs = require('node:fs');
	const { pathToFileURL } = require('node:url');
	const renderer = '/tmp/opencode/cpr-diagram-render';
	const puppeteer = require(`${renderer}/node_modules/puppeteer-core`);
	(async () => {
		const browser = await puppeteer.launch({
			executablePath: '/usr/bin/google-chrome',
			headless: true,
			args: ['--no-sandbox', '--disable-dev-shm-usage', '--allow-file-access-from-files'],
		});
		try {
			const page = await browser.newPage();
			await page.setViewport({ width: 3000, height: 2300, deviceScaleFactor: 1 });
			await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);
			await page.setRequestInterception(true);
			page.on('request', request => {
				if (/^(file:|data:)/.test(request.url())) request.continue();
				else request.abort();
			});
			await page.goto(pathToFileURL(`${renderer}/src/main/webapp/export3.html`).href,
				{ waitUntil: 'load' });
			await page.waitForFunction(() => typeof render === 'function' && typeof Graph === 'function');
			await page.evaluate(xml => {
				render({ xml, format: 'jpg', scale: '1', border: '10',
					bg: '#ffffff', theme: 'light', shadows: '0' });
			}, fs.readFileSync('docs/architecture.drawio', 'utf8'));
			await page.waitForFunction(() => document.querySelector('#LoadingComplete'));
			const bounds = await page.evaluate(() =>
				JSON.parse(document.querySelector('#LoadingComplete').getAttribute('bounds')));
			const clip = { x: 0, y: 0, width: Math.ceil(bounds.x + bounds.width),
				height: Math.ceil(bounds.y + bounds.height) };
			await page.setViewport({ width: clip.width, height: clip.height, deviceScaleFactor: 1 });
			await page.screenshot({ path: 'docs/architecture.jpg', type: 'jpeg', quality: 95, clip });
			console.log(clip);
		} finally {
			await browser.close();
		}
	})().catch(error => { console.error(error); process.exitCode = 1; });
	JS
	```

3. Open the JPEG and check the labels, arrow endpoints, and clipping. Fonts follow the diagram's font stack and the installed system fonts, so another host can produce different text wrapping. This revision renders at 2710 by 2091 pixels.
4. Run the CPR checks:

	```sh
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
	python3 .github/scripts/check_docs.py
	git diff --check
	```
