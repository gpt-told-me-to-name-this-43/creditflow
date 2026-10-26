import { expect, test } from './fixtures.ts'
import { ClientApplicationPage } from './pages/client.ts'
import { QueuePage } from './pages/manager.ts'
import { companies, managers } from './support/companies.ts'

test.beforeEach(async ({ resetDb }) => {
  await resetDb('demo')
})

test('s12: демо-состояние — очередь C3, C6, C7, сводка с историей, у C1 выданный кредит', async ({
  clientPage,
  managerPage,
}) => {
  const queue = new QueuePage(await managerPage(managers.anna))
  await queue.goto()
  for (const name of ['ООО «Склад-М»', 'ИП Орлов Д. С.']) {
    await expect(queue.row(name)).toBeVisible()
  }
  // Рекомендация и кнопки по allowed_actions: C6 — стоп-фактор, только отказ;
  // C7 — ручное рассмотрение без встречного предложения (лимита нет).
  const c6 = await queue.open('ООО «Склад-М»')
  await expect(c6.panel).toContainText('Стоп-фактор')
  await expect(c6.actionButtons()).toHaveText(['Отказать'])
  await queue.goto()
  const c7 = await queue.open('ИП Орлов Д. С.')
  await expect(c7.panel).toContainText('Ручное рассмотрение')
  await expect(c7.actionButtons()).toHaveText(['Одобрить', 'Запросить информацию', 'Отказать'])
  await queue.goto()

  // C3 ждёт ответа клиента на вопрос менеджера.
  await queue.page.getByRole('link', { name: /^Ждут ответа/ }).click()
  await expect(queue.row(companies.C3.name)).toBeVisible()

  // Сводка с историей: решения уже есть — время до решения посчитано.
  await expect(queue.stats).not.toContainText('Медианное время до решенияНет данных')

  const client = await clientPage(companies.C1.login)
  await client.goto('/client')
  await expect(client.getByRole('list', { name: 'Заявки' })).toContainText('Деньги зачислены')
  await client
    .getByRole('list', { name: 'Заявки' })
    .getByRole('listitem')
    .filter({ hasText: 'Деньги зачислены' })
    .getByRole('link')
    .first()
    .click()
  await new ClientApplicationPage(client).expectStatus('Деньги зачислены')
})
