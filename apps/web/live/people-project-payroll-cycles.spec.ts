import { expect, test, type Page, type Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/api/v1/people-project-payroll";
async function fill(form: Locator, values: Record<string, string>) {
  for (const [label, value] of Object.entries(values)) await form.getByLabel(label, { exact: true }).fill(value);
}
async function login(page: Page, username: string) {
  await page.goto(`${base}/people-project-payroll`);
  const logout=page.getByRole("button",{name:"Sign out",exact:true});
  if (await logout.count()) await logout.click();
  const form=page.getByRole("form",{name:"Sign in",exact:true});
  await fill(form,{Tenant:tenant!,Username:username,Password:password!});
  await form.getByRole("button",{name:"Sign in",exact:true}).click();
  const privileged=page.getByRole("form",{name:"Verify financial authority",exact:true});
  await privileged.getByLabel("Password",{exact:true}).fill(password!);
  await privileged.getByRole("button",{name:"Verify financial authority",exact:true}).click();
  await expect(privileged).toHaveCount(0);
  const scope=page.getByRole("form",{name:"Apply scope",exact:true});
  await expect(scope.getByLabel("Workspace ID",{exact:true})).toHaveValue("work");
  await scope.getByRole("button",{name:"Apply scope",exact:true}).click();
  await expect(page.getByRole("combobox",{name:"Employee source",exact:true})).toBeVisible();
}
async function command(page: Page, container: Locator, name: string, path: string, key: string, lose=false) {
  let original: unknown, rawBody="", finish!:()=>void;
  const committed=new Promise<void>(resolve=>{finish=resolve;});
  if (lose) await page.route(`**${root}${path}`,async route=>{
    if(route.request().method()!=="POST") {await route.continue();return;}
    rawBody=route.request().postData()!;
    const response=await route.fetch();expect(response.status(),await response.text()).toBe(200);
    original=(await response.json())[key];await route.abort("failed");finish();
  },{times:1});
  const response=lose?null:page.waitForResponse(reply=>reply.url().endsWith(root+path)&&reply.request().method()==="POST");
  await container.getByRole("button",{name,exact:true}).click();
  if(lose) {
    await committed;
    const retry=page.getByRole("button",{name:"Retry same retained command",exact:true});await expect(retry).toBeVisible();
    const replay=page.waitForResponse(reply=>reply.url().endsWith(root+path)&&reply.request().method()==="POST");await retry.click();
    const reply=await replay;expect(reply.status(),await reply.text()).toBe(200);expect(reply.request().postData()).toBe(rawBody);
    const value=(await reply.json())[key];expect(value).toEqual(original);return value;
  }
  const reply=await response!;expect(reply.status(),await reply.text()).toBe(200);return (await reply.json())[key];
}
async function selectEmployee(page: Page,id: string) {
  const select=page.getByRole("combobox",{name:"Employee source",exact:true}).first();
  await expect(select.locator(`option[value="${id}"]`)).toHaveCount(1);await select.selectOption(id);
}
async function selectPlan(page: Page,id: string) {
  const select=page.getByRole("combobox",{name:"Financial source",exact:true});
  await expect(select.locator(`option[value="${id}"]`)).toHaveCount(1);await select.selectOption(id);
  const proof=page.getByRole("region",{name:"Financial source",exact:true});await expect(proof).toContainText(id);return proof;
}
async function phase(page: Page,id: string,action:"review"|"post",lose=false) {
  await login(page,action==="review"?"checker":"poster");
  const proof=await selectPlan(page,id);
  const value=await command(page,proof,action==="review"?"Review exact original source":"Post native GL effect",`/plans/${id}/${action}`,"plan",lose);
  await expect(proof).toContainText(id);return value;
}
test("real governed project time hourly accrual partial final wages and retained financial command",async({page})=>{
  test.setTimeout(420_000);expect(base&&tenant&&password,"Owned HTTPS dual-role fixture required").toBeTruthy();
  const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
  await login(page,"maker");
  const scopeHeaders={"X-ReconForge-Tenant":tenant!,"X-ReconForge-Workspace":"work","X-ReconForge-Organization":"org","X-ReconForge-Legal-Entity":"entity"};
  const budgetReply=await page.request.get(`${base}/api/v1/budget-control/envelopes?workspace_id=work&organization_id=org&legal_entity_id=entity`,{headers:scopeHeaders});
  expect(budgetReply.status()).toBe(200);const budgets=(await budgetReply.json()).envelopes;expect(budgets).toHaveLength(1);const budget=budgets[0];
  const projects:string[]=[];
  for(const code of ["P1","P2"]) {
    const form=page.getByRole("form",{name:"Bind native Project dimension",exact:true});
    await fill(form,{"Project code":code,"Existing Project dimension code":"PROJECT","Existing dimension value":code});
    projects.push((await command(page,form,"Bind native Project dimension","/projects","project")).id);
  }
  const employees:string[]=[],times:string[]=[];
  for(const [index,rate,first,last] of [[1,"1001","61","90"],[2,"999","15","60"]] as const) {
    const person=page.getByRole("form",{name:"Register employee",exact:true});
    await fill(person,{"Employee code":`E${index}`,"Private employee name":`Synthetic person ${index}`,"Linked user ID (optional)":index===1?"maker":""});
    const employee=await command(page,person,"Register employee","/employees","employee");employees.push(employee.id);await selectEmployee(page,employee.id);
    const agreement=page.getByRole("form",{name:"Capture effective hourly agreement",exact:true});
    await fill(agreement,{"Effective from":"2026-10-01","Effective through":"2026-10-31","Hourly rate in exact minor units":rate,"Functional currency":"USD",Reason:"Synthetic effective contract"});
    await command(page,agreement,"Capture effective hourly agreement",`/employees/${employee.id}/employment`,"employment");
    const time=page.getByRole("form",{name:"Submit whole time document",exact:true});
    await fill(time,{"Time business date":"2026-10-03",Reason:"Original approved project labor"});
    // The retained form supports full multi-project interval documents.
    while(await time.getByRole("group").count()<2) await time.getByRole("button",{name:"Add project interval",exact:true}).click();
    await time.getByRole("group").nth(0).getByRole("combobox",{name:"Original project",exact:true}).selectOption(projects[0]);
    await fill(time.getByRole("group").nth(0),{"UTC start minute (0–1439)":"0","UTC end minute (1–1440)":first});
    await time.getByRole("group").nth(1).getByRole("combobox",{name:"Original project",exact:true}).selectOption(projects[1]);
    await fill(time.getByRole("group").nth(1),{"UTC start minute (0–1439)":first,"UTC end minute (1–1440)":last});
    times.push((await command(page,time,"Submit whole time document","/times","time")).id);
  }
  const own=page.getByRole("form",{name:"Approve exact time",exact:true});
  await own.getByRole("combobox").selectOption(times[0]);expect(own.getByRole("button",{name:"Approve exact time",exact:true})).toBeDisabled();
  await login(page,"checker");
  for(const id of times) {
    const form=page.getByRole("form",{name:"Approve exact time",exact:true});await form.getByRole("combobox").selectOption(id);
    await command(page,form,"Approve exact time",`/times/${id}/approve`,"time");
  }
  await login(page,"maker");
  const accrual=page.getByRole("form",{name:"Reserve budget and prepare accrual",exact:true});
  await expect(accrual.getByRole("checkbox")).toHaveCount(2);for(const checkbox of await accrual.getByRole("checkbox").all()) await checkbox.check();
  await fill(accrual,{"Approved budget ID":budget.id,"Current budget version":String(budget.row_version),"Open fiscal period":"period","Posting date":"2026-10-04","Native journal":"STOCK","Project labor expense account":"LABOR","Wage liability account":"WAGES","Cash account":"CASH"});
  const payrun=await command(page,accrual,"Reserve budget and prepare accrual","/payruns","plan",true);expect(payrun.amount_minor).toBe("2501");
  const prepared=page.getByRole("region",{name:"Financial source",exact:true});await expect(prepared).toContainText(payrun.id);
  expect(prepared.getByRole("button",{name:"Review exact original source",exact:true})).toBeDisabled();
  await phase(page,payrun.id,"review");await phase(page,payrun.id,"post",true);
  for(const [index,amounts] of [[1,["1000"]],[2,["502","999"]]] as const) {
    await login(page,"maker");await selectPlan(page,payrun.id);
    const payment=page.getByRole("form",{name:"Prepare partial or final payment",exact:true});
    await fill(payment,{"Open fiscal period":"period","Posting date":index===1?"2026-10-05":"2026-10-06"});
    while(await payment.getByRole("group").count()<amounts.length) await payment.getByRole("button",{name:"Add project interval",exact:true}).click();
    for(let i=0;i<amounts.length;i++) {
      await payment.getByRole("group").nth(i).getByRole("combobox",{name:"Employee source",exact:true}).selectOption(employees[i]);
      await fill(payment.getByRole("group").nth(i),{"Employee payment in exact minor units":amounts[i]});
    }
    const source=await command(page,payment,"Prepare partial or final payment",`/payruns/${payrun.id}/payments`,"plan");
    await phase(page,source.id,"review");await phase(page,source.id,"post",index===2);
  }
  await login(page,"maker");const source=await selectPlan(page,payrun.id);
  const response=page.waitForResponse(reply=>reply.url().endsWith(`/payruns/${payrun.id}/evidence`));
  await source.getByRole("button",{name:"Load private financial evidence",exact:true}).click();
  const evidence=await (await response).json();expect(evidence.native_effects).toHaveLength(3);
  await test.info().attach("hc1-original-native-financial-evidence",{body:JSON.stringify(evidence),contentType:"application/json"});
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([]);
  await page.setViewportSize({width:390,height:844});await page.getByRole("button",{name:"Switch language",exact:true}).click();
  await expect(page.getByRole("heading",{name:"الأفراد ووقت المشروعات ومحاسبة الأجور",exact:true})).toBeVisible();
  await expect(page.locator("main#main-content")).toHaveAttribute("dir","rtl");
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([]);expect(errors).toEqual([]);
});
