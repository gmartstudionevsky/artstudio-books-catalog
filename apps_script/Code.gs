/**
 * ARTSTUDIO Books Google Sheets integration.
 *
 * Что делает:
 * - добавляет меню в Google Sheets;
 * - запускает GitHub Actions workflow_dispatch;
 * - не парсит страницы сам, тяжелая работа остается в GitHub Actions.
 */

const ARTSTUDIO_BOOKS_PROPS = {
  owner: 'ARTSTUDIO_GITHUB_OWNER',
  repo: 'ARTSTUDIO_GITHUB_REPO',
  workflow: 'ARTSTUDIO_GITHUB_WORKFLOW',
  branch: 'ARTSTUDIO_GITHUB_BRANCH',
  token: 'ARTSTUDIO_GITHUB_TOKEN'
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('ARTSTUDIO Books')
    .addItem('Запустить обновление', 'runBooksWorkflowDefault')
    .addItem('Запустить тест на 10 строк', 'runBooksWorkflowTest')
    .addSeparator()
    .addItem('Настроить GitHub Actions', 'setupArtstudioBooksIntegration')
    .addItem('Проверить настройки', 'showArtstudioBooksSettings')
    .addToUi();
}

function setupArtstudioBooksIntegration() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();

  const owner = promptValue_(ui, 'GitHub owner', props.getProperty(ARTSTUDIO_BOOKS_PROPS.owner) || '');
  if (!owner) return;
  const repo = promptValue_(ui, 'GitHub repo', props.getProperty(ARTSTUDIO_BOOKS_PROPS.repo) || 'artstudio-books-catalog');
  if (!repo) return;
  const workflow = promptValue_(ui, 'Workflow file name', props.getProperty(ARTSTUDIO_BOOKS_PROPS.workflow) || 'update-books.yml');
  if (!workflow) return;
  const branch = promptValue_(ui, 'Branch/ref', props.getProperty(ARTSTUDIO_BOOKS_PROPS.branch) || 'main');
  if (!branch) return;
  const token = promptValue_(ui, 'GitHub token', props.getProperty(ARTSTUDIO_BOOKS_PROPS.token) || '');
  if (!token) return;

  props.setProperty(ARTSTUDIO_BOOKS_PROPS.owner, owner);
  props.setProperty(ARTSTUDIO_BOOKS_PROPS.repo, repo);
  props.setProperty(ARTSTUDIO_BOOKS_PROPS.workflow, workflow);
  props.setProperty(ARTSTUDIO_BOOKS_PROPS.branch, branch);
  props.setProperty(ARTSTUDIO_BOOKS_PROPS.token, token);

  ui.alert('Готово', 'Настройки сохранены. Теперь можно запускать обновление из меню ARTSTUDIO Books.', ui.ButtonSet.OK);
}

function showArtstudioBooksSettings() {
  const props = PropertiesService.getScriptProperties();
  const owner = props.getProperty(ARTSTUDIO_BOOKS_PROPS.owner) || '—';
  const repo = props.getProperty(ARTSTUDIO_BOOKS_PROPS.repo) || '—';
  const workflow = props.getProperty(ARTSTUDIO_BOOKS_PROPS.workflow) || '—';
  const branch = props.getProperty(ARTSTUDIO_BOOKS_PROPS.branch) || '—';
  const token = props.getProperty(ARTSTUDIO_BOOKS_PROPS.token) ? 'сохранен' : 'не задан';

  SpreadsheetApp.getUi().alert(
    'ARTSTUDIO Books settings',
    'Owner: ' + owner + '\nRepo: ' + repo + '\nWorkflow: ' + workflow + '\nBranch: ' + branch + '\nToken: ' + token,
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function runBooksWorkflowDefault() {
  runBooksWorkflow_({
    force_refresh: 'false',
    max_rows: '0',
    include_only_checked: 'false',
    enable_playwright_fallback: 'false'
  });
}

function runBooksWorkflowTest() {
  runBooksWorkflow_({
    force_refresh: 'true',
    max_rows: '10',
    include_only_checked: 'false',
    enable_playwright_fallback: 'false'
  });
}

function runBooksWorkflow_(inputs) {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();
  const owner = props.getProperty(ARTSTUDIO_BOOKS_PROPS.owner);
  const repo = props.getProperty(ARTSTUDIO_BOOKS_PROPS.repo);
  const workflow = props.getProperty(ARTSTUDIO_BOOKS_PROPS.workflow);
  const branch = props.getProperty(ARTSTUDIO_BOOKS_PROPS.branch) || 'main';
  const token = props.getProperty(ARTSTUDIO_BOOKS_PROPS.token);

  if (!owner || !repo || !workflow || !token) {
    ui.alert('Нужна настройка', 'Сначала запустите: ARTSTUDIO Books → Настроить GitHub Actions.', ui.ButtonSet.OK);
    return;
  }

  const endpoint = 'https://api.github.com/repos/' + owner + '/' + repo + '/actions/workflows/' + workflow + '/dispatches';
  const payload = {
    ref: branch,
    inputs: inputs
  };

  const response = UrlFetchApp.fetch(endpoint, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    muteHttpExceptions: true
  });

  const code = response.getResponseCode();
  if (code >= 200 && code < 300) {
    SpreadsheetApp.getActiveSpreadsheet().toast('Workflow запущен. PDF появится в GitHub Actions artifacts / Drive.', 'ARTSTUDIO Books', 8);
  } else {
    ui.alert('Ошибка запуска', 'GitHub вернул код ' + code + ':\n' + response.getContentText(), ui.ButtonSet.OK);
  }
}

function promptValue_(ui, title, defaultValue) {
  const result = ui.prompt(title, 'Введите значение:', ui.ButtonSet.OK_CANCEL);
  if (result.getSelectedButton() !== ui.Button.OK) {
    return null;
  }
  const value = result.getResponseText().trim();
  return value || defaultValue || null;
}
