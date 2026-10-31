# AgroLand — Agentic Commerce on Cardano

Help the AgroLand team build a working product for the Cardano track of the TUM Blockchain & AI Hackathon, 30–31 October 2026 in Munich. Turn the existing AgroLand codebase, land data, documents, and project context into useful, verifiable results for landowners, tenant farms, and energy developers, with real payments on Cardano preprod.

You are receiving the existing AgroLand codebase and project context. Your task is to understand it, combine three user-facing products into one working system, improve the frontend, and prepare a complete integration with Masumi and Sokosumi for the Cardano track. We need a finished project that can run on our existing server once the necessary access has been configured.

This is an implementation, verification, and deployment-preparation task. Independently choose a sensible architecture, agent structure, project layout, and integration approach. The context, product goals, and acceptance criteria are defined below. Apart from the explicit integration requirements, we are not prescribing specific features, technologies, or a fixed number of services.

## 0. Required guides, developer skills, and integration workflow

Read the official agent guide first:

- Official guide: https://www.masumi.network/tum-hackathon/agent-guide.md
- Cardano track rules: https://hackathon.tum-blockchain.com/prizes#cardano
- Submission rules: https://hackathon.tum-blockchain.com/prizes#how-to-submit

**You must use the Cardano Developer Skills for the Cardano implementation.** Read the repository instructions, install or enable the appropriate plugin for your environment, and load and apply the relevant skills before implementing or changing Cardano-related code. Do not merely include the link in the README; use the skills during implementation and verification.

- Cardano Developer Plugin for Claude Code and Codex: https://github.com/cardano-foundation/cardano-dev-skills
- Masumi hackathon skill: https://www.masumi.network/tum-hackathon/skill/SKILL.md
- Masumi skills installation command: `npx skills add https://github.com/masumi-network/masumi-skills --skill masumi`
- Sokosumi MCP server: https://www.masumi.network/dev/sokosumi/mcp — sign in with OAuth; no API key is required for this MCP connection.

Read and use the Masumi hackathon skill and the relevant Masumi and Sokosumi skills. Read the Sokosumi skills and command help before making account changes. If a required skill cannot be loaded, identify the concrete blocker and continue work that does not depend on it; do not claim to have used it.

### Paid per job: Masumi on Sokosumi

- Use https://github.com/masumi-network/tum-hackathon-quickstart. Read its `README` and `AGENTS.md` before setup, and adapt the existing template to AgroLand.
- Use Node.js 24, the quickstart's pinned dependencies, and Sokosumi CLI 1.0.4 for this integration. Preserve compatible existing services where appropriate.
- Use my own preprod account and Personal Workspace. Account signup: https://preprod.sokosumi.com/signup.
- Reuse saved resources when resuming work. Verify existing accounts, workspace references, registrations, Coworkers, and task identifiers before creating replacements or duplicates.
- First verify a model reply and one execution-only Coworker Task. Add the preprod payment setup only after I authorize it.
- Prepare all code, configuration templates, and instructions that can be completed without account access or payment authorization.

### Paid per request: x402

If using x402 for an appropriate paid request, start from https://developers.cardano.org/x402/ and the `x402-express` or `x402-next` template. Configure a Blockfrost preprod key securely and obtain test ADA from the faucet. Explain how this request fits the product and its payment model. An x402 integration does not remove the required Masumi/Sokosumi integration described below.

To qualify, complete at least one real paid job or paid request on Cardano preprod and save its payment transaction hash. Once the necessary access and authorization are available, return the completed Task ID or request details, the result, the payment transaction hash, the exact run commands, and any remaining setup steps. Never fabricate qualification evidence.

Keep credentials out of chat, logs, frontend code, and Git.

## 1. Supplied materials and how to handle the source code

- `AgroLand.tar` — the existing map interface, landowner and tenant-farm workflows, the developer interface, and part of the backend.
- `case.tar.gz` — a separate original implementation of the farm lease-checking workflow. Some of this logic has already been moved into AgroLand.
- `geo-pooler.tar` — site auditing, nearby-project discovery, consent/NDA/payment flows, joint-project calculations, German and Indian implementations, and a Sokosumi adapter.
- `kontekst-proekta-agent-proveryaet-zemlyu.md` — background, research, ideas, and previous decisions.

Start by inspecting the actual code, data, tests, launch instructions, and existing integrations. Documentation may lag behind the implementation. Archives may contain duplicates, temporary solutions, configuration files, and secrets. Preserve useful logic and data, and resolve conflicting implementations. Do not include private configuration in the final public project or expose secrets in responses or logs.

This prompt reflects our current decisions. Older context may have proposed one primary workflow, Germany-only coverage, or postponing other capabilities. The current requirements are different: all three workflows have equal priority, and both Germany and India must be supported.

## 2. The product we are building

AgroLand helps people work with land: understand a parcel's condition, check its associated documents and costs, assess an energy site, and prepare the next step. Shared entities and results should connect the workflows into one product, while each workflow remains useful on its own.

A landowner wants to assess a parcel, understand the findings and limitations, attach documents, and offer the land to interested parties. The owner retains control over publication and information disclosure.

A tenant farm wants to compare contracts, parcel data, and actual land use; identify discrepancies and potentially unnecessary costs; see deadlines; and receive a report with reminders. Distinguish an identified discrepancy, an opportunity for negotiation, and savings actually achieved.

An energy developer wants to assess a site for solar, wind, or a combination of both; find suitable nearby projects; safely arrange information sharing; and receive a preliminary joint-project calculation with supporting documents.

All three workflows must be fully functional entry points into the product. Do not reduce two of them to inactive cards or promises of future features. Do not require users to complete someone else's workflow to access their own.

Design real transitions between the workflows. An owner's listing, a tenant's lease, and a site in a developer's portfolio have different meanings. Publishing a parcel does not transfer rights to it, and farm data must not automatically become public. The proximity of two sites alone does not establish a continuous land block or prove the economic benefit of combining them.

## 3. Readiness level and geographic coverage

We are preparing a working hackathon project. Demonstration parcels, owners, contracts, and prepared data snapshots are acceptable if clearly labeled. Business logic, transitions between services, result generation, Masumi/Sokosumi integrations, and the payment process must be real.

Even with demonstration data, perform actual calculations and call our working services. Client-side simulations of neighbors, signatures, payment statuses, or completed results do not constitute a working workflow. Two test identities may be used to demonstrate a genuine process involving two parties.

Support Germany and India across all three workflows. Assess the actual coverage of the existing Indian modules and regions. Use appropriate data, units, currencies, rules, and documents for each country. Where prepared data is necessary, use an honestly labeled demonstration dataset. An unavailable registry or data source must appear as a limitation, rather than being turned into an invented fact. Do not promise verification of ownership, planning permission, or grid-connection availability unless supported by sources.

The working name is AgroLand. The user interface must be in English. Internal team documentation may be in Russian; prepare a clear English project description for the judges.

## 4. Frontend: preserve the concept and build a usable product

Study the existing design and preserve its recognizable concept: working with land through a map, agent conversations, cards, and understandable results. Rework components, navigation, and states so the application feels cohesive and convenient. Use Sokosumi as a reference for clarity and visual polish. Examine its current interface where accessible, and adapt useful principles to AgroLand while retaining our own brand.

Build a complete public landing page: a clear explanation of the value, three equally prominent workflows, example results, an explanation of the process and payment, and a clear entry into the application. The working interface must be visually consistent with the landing page.

Within the application, users must be able to find the right agent, create a task, select a parcel or provide input, see the price before payment, follow execution, and open the result. Connect the map, documents, task history, payments, and developer projects. Supplement conversations with forms, cards, and actions wherever they are more convenient than free text.

Account for first use, returning to unfinished work, waiting for another party, external-source failures, and payment failures. States must be understandable and persist after a page refresh. Ensure comfortable use on a typical laptop and appropriate adaptation to smaller screens. Verify the result in a browser.

Distinguish a preliminary geometric signal, an audit conclusion, and data quality or completeness. A green card must not appear to provide a universal guarantee. At the same time, avoid overwhelming users with internal terminology and technical settings.

## 5. Masumi, Sokosumi, and our own website

This is a central part of the task. Independently design and implement a meaningful connection between these three components:

- Our website is a complete external product interface through which users can complete all three workflows.
- Sokosumi provides a real way to discover and invoke our agent services, receive results, and continue working within the platform's capabilities.
- Masumi/Cardano provides real payment for specific services, with a correct connection between the order, the result, and payment evidence.

Our website and Sokosumi must use the same execution system and produce consistent results. Do not create two diverging versions of the product. Define what runs on our server, what is registered in Masumi, what is presented in Sokosumi, and how task and user identifiers are linked. Registration must not be presented as executable-code hosting, and a Sokosumi listing must have working execution behind it.

We are not fixing the number of agents, Coworkers, or paid registrations in advance. Three user workflows do not necessarily require three technical agents. Decide which capabilities should be standalone agent services and which should be internal tools or stages. The composition must make product sense and be clearly explained in the README.

Study current official interfaces, limitations, SDKs, and registration requirements. Use compatible, verified versions, following the required quickstart runtime and pinned dependencies. If the platform limits part of a user process, implement a working supported approach and explain the boundary. Do not substitute a visually similar interface for a real integration.

Choose the appropriate degree of agent autonomy. Calculations and verifiable rules may remain deterministic. A language-model agent must have real responsibilities and tools; do not simulate independent decision-making with scripted replies. Complete the initial model-reply and execution-only Coworker Task checks before proceeding to authorized payment setup.

## 6. Payments and Cardano track requirements

Use Cardano preprod. Provide a real payment path for the paid services in each of the three workflows. Price, currency, payment timing, and service-completion conditions must be consistent across registration, backend, our interface, and Sokosumi. If several internal stages belong to one paid order, do not charge again for the same result.

Define exactly what the customer pays for: an audit, a lease check, information disclosure, or another useful result. A correct negative report may still constitute a successfully completed service. Verification must check the promised deliverable. A hash confirms correspondence with recorded data, but does not itself prove that the data is true.

Handle successful completion, rejection, timeout, unavailable data, and any refund or dispute mechanisms provided by the protocol. Distinguish report readiness from transaction confirmation and the seller's receipt of funds. Repeated requests, page refreshes, or restarts must not cause duplicate payments. Consent and document signing must reflect actions by the appropriate parties.

Use these official sources:

- Official TUM agent guide: https://www.masumi.network/tum-hackathon/agent-guide.md
- Cardano track rules: https://hackathon.tum-blockchain.com/prizes#cardano
- Submission rules: https://hackathon.tum-blockchain.com/prizes#how-to-submit
- Masumi TUM hackathon page: https://www.masumi.network/tum-hackathon
- Official quickstart: https://github.com/masumi-network/tum-hackathon-quickstart
- Masumi documentation: https://www.masumi.network/dev/masumi/documentation
- Masumi hackathon skill: https://www.masumi.network/tum-hackathon/skill/SKILL.md
- Masumi skills: https://github.com/masumi-network/masumi-skills
- Sokosumi preprod: https://preprod.sokosumi.com/
- Sokosumi MCP: https://www.masumi.network/dev/sokosumi/mcp
- Cardano Developer Skills: https://github.com/cardano-foundation/cardano-dev-skills
- Cardano x402 documentation: https://developers.cardano.org/x402/

A previous review found a discrepancy: the track page required at least one paid preprod job or request with a transaction hash, while the Masumi guide described payment testing as optional. Recheck the current rules. Regardless of that discrepancy, our acceptance target is real paid integrations and at least one completed paid job or request on Cardano preprod with its actual transaction hash.

Prepare evidence of the completed task or request, its result, the transaction, and receipt of payment. Account for the submission format: a video of up to 2.5 minutes, a Devfolio description, and a public repository with a README. Verify these details against the current submission rules. Show a specific customer, useful work, and the connection between payment and the result.

## 7. Observations about the current state: starting points for verification

A preliminary review found the following. Verify these observations independently against the supplied code:

- The farm workflow exists both separately and inside AgroLand. Choose a maintained implementation and preserve its behavior.
- The developer interface is connected to the geographic auditor, while subsequent stages are still simulated even though their backend already exists.
- Landowner and farm payments are currently demonstrations.
- The German auditor and NDA service configurations already contain different Masumi IDs and have payment bypass disabled. This does not prove that registration is current or that a payment has succeeded.
- The existing Sokosumi worker calls an internal unpaid audit. The paid workflow from our interface also needs to be checked for completeness.
- Displayed prices and currencies differ between configuration and the interface.
- Different startup methods do not guarantee one working system. The Indian stack configuration requires separate verification.

Do not treat these observations as a finished technical specification for a fixed list of changes. Develop your own understanding and fix the causes of the gaps. Reuse existing registrations and configuration where possible after checking their validity.

## 8. What “add credentials and run” means

After your work, starting the project must not require additional integration code or manual source-code edits. Prepare it for our existing server with a reproducible build, environment configuration, persistent storage, service-readiness checks, and clear startup, update, and diagnostic procedures. Choose an appropriate deployment approach.

Separately list everything the team must provide or do: required access, domains or addresses, server configuration, registrations, Workspace permissions, test funds, and other external prerequisites. Do not imply that API keys are sufficient if account sign-in, access approval, or funding a test wallet is also required. Prepare the necessary tools and instructions. For Sokosumi MCP, document OAuth sign-in rather than requesting an API key.

Store keys and private credentials outside the frontend and repository. Include safe configuration templates in the final project. Account for different users' access to documents, parcels, tasks, and deals in a real public demo. A local workspace originally intended for a single operator must not simply be exposed to the internet with private data inside it.

This task prepares the project for deployment. Publishing, changing the live server, and operating our accounts are separate steps after the necessary access is provided and the specific action is authorized. Preprod payment setup requires my authorization after the model reply and execution-only Coworker Task have been verified. Missing access must not prevent completion of the code and local verification.

## 9. How to verify readiness

Verify end-to-end workflows for the landowner, tenant farm, and developer, including both German and Indian variants. Check result consistency between our interface and the Sokosumi integration, state persistence, access restrictions, and failure handling. Cover meaningful calculations and critical payment transitions with appropriate tests.

Provide a reproducible demonstration dataset that the team can use to show the whole system. If you use mocks to test internal errors, label that work as testing. Such a test is not evidence of a successful external payment.

Without real access, you may confirm local readiness and the correctness of the prepared integration within the available conditions. Separately identify checks that require connected accounts and preprod access. Do not invent successful transactions, registrations, Task IDs, or verification results. Once the necessary access is available, final verification must be possible without additional programming.

For the Cardano integration, record the initial model-reply check, the execution-only Coworker Task, and, after authorization, the completed paid preprod job or request. Retain the actual result, task or request identifiers, payment transaction hash, and commands needed to reproduce the run.

## 10. Required deliverables

Deliver one complete project, an improved interface with a landing page, all three working workflows, prepared integrations, and documentation for our server.

The README must contain a clear numbered catalog: “Agent 1,” “Agent 2,” “Agent 3,” and so on, based on the actual architecture. For each agent, specify its name, purpose, input, output, relationships with other agents, invocation method from our application and Sokosumi, whether it offers a paid Masumi service, configuration, and verification procedure. The number four from our earlier example is not a requirement. Separately identify internal services that are not presented to users as standalone agents.

Also document the overall system architecture, setup from scratch, configuration without secrets, Masumi/Sokosumi connection procedures, team actions required before deployment, demonstration workflows, country coverage, limitations, and checks actually performed. Document which Cardano Developer Skills and Masumi/Sokosumi skills were used and where they informed the implementation. Prepare a draft Devfolio description and a video script that gives equal importance to all three product directions.

Include the completed Task ID or request details, the useful result, the actual payment transaction hash, the exact run commands, and any remaining external setup steps. If external access or authorization is still missing, mark the affected evidence as pending and explain exactly what is needed to obtain it.

In the final report, clearly distinguish:

- Implemented and verified.
- Ready but awaiting external access or authorization.
- Not implemented.

If anything remains unfinished, explain the specific reason. Do not present a list of future improvements as a completed integration.

Start by reading the official agent guide and required skills, inspecting the supplied materials, and briefly stating the gaps you found and the structure you selected. Then implement, verify, and prepare the project for launch. Make routine technical decisions independently. Ask for clarification only when it materially changes the product or requires an unavailable external resource, and obtain authorization for the account, payment, and deployment actions specified above. Continue all other work in the meantime.
