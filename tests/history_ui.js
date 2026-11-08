// Real browser + temporary dashboard API/database, no live dashboard mutation.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs'), path = require('path'), os = require('os');
const assert = require('node:assert/strict');
(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(),'history-ui-'));
  const ready = path.join(tmp,'port');
  const child = spawn(process.env.DASHBOARD_TEST_PYTHON || '/home/server/odoo-17.0/.venv/bin/python', [path.join(__dirname,'history_fixture.py'),ready]);
  let logs = ''; child.stderr.on('data',d=>logs+=d); child.stdout.on('data',d=>logs+=d);
  let browser;
  try {
    for(let i=0;i<100&&!fs.existsSync(ready);i++) await new Promise(r=>setTimeout(r,100));
    assert(fs.existsSync(ready),logs);
    const base = 'http://127.0.0.1:'+fs.readFileSync(ready,'utf8');
    browser = await chromium.launch({headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    // Unrelated panels should not inspect the user's sessions or Odoo processes.
    await page.route('**/api/**',route => route.request().url().includes('/api/flow') ? route.continue() : route.fulfill({json:[]}));
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base);
    await page.locator('#tab-flows').click();
    await page.locator('.run-row').nth(2).waitFor();
    assert.equal(await page.locator('.run-row').count(),3);
    await page.locator('.flow-row').filter({hasText:'invoice-confirm'}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.run-row').length===2);
    await page.locator('[data-run-id="fixture-failed"]').click();
    await page.locator('#failure-summary').getByText('Expected 10; found 20',{exact:true}).waitFor();
    await page.locator('[data-flow-snapshot] > summary').click();
    assert((await page.locator('#failure-summary').innerText()).includes('Failed assertion'));
    await page.locator('[data-rpc-id] > summary').click();
    assert((await page.locator('[data-rpc-id]').innerText()).includes('Python execution · captured'));
    await page.getByText('Executed call sequence', {exact:true}).click();
    assert((await page.locator('[data-rpc-id]').innerText()).includes('SaleOrder.create_invoices'));
    assert((await page.locator('[data-rpc-id]').innerText()).includes('custom/invoice.py:42'));
    assert.equal(await page.locator('#flow-run-detail script').count(),0);
    await page.evaluate(()=>loadFlows());
    assert(await page.locator('[data-rpc-id]').getAttribute('open') !== null);
    assert(await page.locator('[data-python-sequence]').getAttribute('open') !== null);
    assert((await page.locator('#flow-run-detail').innerText()).includes('# historical failed'));
    assert(!(await page.locator('#flow-run-detail').innerText()).includes('current definition'));
    assert.equal(await page.locator('#flow-run-detail a[href^="/api/"]').count(),4);
    await page.screenshot({path:path.join(tmp,'history-desktop.png'),fullPage:true});
    await page.locator('#flow-status-filter').selectOption('passed');
    await page.waitForFunction(()=>document.querySelectorAll('.run-row').length===1 && document.querySelector('.run-row').dataset.runId==='fixture-passed');
    await page.locator('[data-run-id="fixture-passed"]').click();
    await page.waitForFunction(()=>document.querySelector('#flow-run-detail').textContent.includes('# historical passed'));
    await page.locator('#flow-definition summary').click();
    assert((await page.locator('#flow-preview-content').innerText()).includes('current definition'));
    // Delete via API and refresh UI: historical runs remain discoverable.
    assert.equal((await page.request.delete(base+'/api/flows/invoice-confirm')).status(),200);
    await page.evaluate(()=>loadFlows());
    assert.equal(await page.locator('.flow-row').filter({hasText:'invoice-confirm'}).count(),1);
    await page.locator('.flow-row').filter({hasText:'old-flow'}).click();
    await page.locator('#flow-status-filter').selectOption('');
    await page.waitForFunction(()=>document.querySelectorAll('.run-row').length===1);
    await page.locator('.run-row').click();
    await page.getByText('No flow snapshot was captured for this run.').waitFor();
    await page.setViewportSize({width:1440,height:700});
    await page.locator('.flow-row').filter({hasText:'long-definition-no-runs'}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.run-row').length===0);
    await page.locator('#flow-definition').evaluate(el=>el.open=true);
    const geometry = await page.evaluate(()=>({
      paginationBottom:document.querySelector('#flow-runs-prev').getBoundingClientRect().bottom,
      definitionTop:document.querySelector('#flow-definition').getBoundingClientRect().top,
      detailBottom:document.querySelector('#flow-run-detail').getBoundingClientRect().bottom,
    }));
    assert(geometry.paginationBottom<=geometry.definitionTop, 'pagination overlaps definition: '+JSON.stringify(geometry));
    assert(geometry.detailBottom<=geometry.definitionTop, 'run details overlap definition: '+JSON.stringify(geometry));
    await page.screenshot({path:path.join(tmp,'long-definition.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(tmp,'history-mobile.png'),fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'horizontal overflow');
    assert.deepEqual(errors,[]);
    console.log('PASS history UI: library, filters, historical snapshots, errors, artifact links, legacy runs, definition deletion, mobile layout');
    console.log('Screenshots: '+tmp);
  } finally {
    if(browser) await browser.close(); child.kill();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
