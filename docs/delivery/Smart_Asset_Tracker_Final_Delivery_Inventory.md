# Final Delivery Plan and Materials Inventory
## AWS Smart Asset Lifecycle Tracker Group 2

**Snapshot date:** 8 October 2026

**Prepared by:** Group 2

**Document maintainer:** Group 2

**Status:** Draft for team review

This index references the existing repository materials identified in the PR #43 review and lists the remaining submission confirmations. File presence alone does not establish readiness of its contents or the deployed application.

## 1 Delivery links

| Item | Link or value |
| --- | --- |
| Repository | [saltracker](https://github.com/PellizzoniCode/saltracker) |
| Working application URL | To be confirmed by the team after the final deployment |
| Submitted branch and commit SHA | To be recorded after the final changes are merged |
| Open issues | [Open issues](https://github.com/PellizzoniCode/saltracker/issues?q=is%3Aissue%20is%3Aopen) |
| Closed issues | [Closed issues](https://github.com/PellizzoniCode/saltracker/issues?q=is%3Aissue%20is%3Aclosed) |

## 2 Submission materials

Links below resolve from this document in `docs/delivery/`. Confirm the remaining locations before submission; proposed files are explicitly marked.

| Material | Repository location or remaining confirmation |
| --- | --- |
| Source code and setup instructions | Repository and [README.md](../../README.md) |
| Infrastructure as code | [infrastructure/template.yaml](../../infrastructure/template.yaml) |
| Architecture diagram | [docs/architecture/](../architecture/); select the existing Week 4 PNG and confirm it matches the final deployment |
| DynamoDB data model | [docs/data-model.md](../data-model.md) |
| Cognito groups and permissions | [docs/role-permissions.md](../role-permissions.md) |
| Monitoring documentation | [docs/cloudwatch-monitoring.md](../cloudwatch-monitoring.md) |
| Deployment instructions | [README.md](../../README.md), [scripts/dev.sh](../../scripts/dev.sh) and [monitoring setup](../cloudwatch-monitoring.md); final CI/CD documentation remains to be confirmed |
| AWS cost estimate | [docs/estimated-monthly-aws-cost.md](../estimated-monthly-aws-cost.md) |
| AWS Pricing Calculator exports | [PDF](../cost-estimate/group2-aws-cost-estimate.pdf), [CSV](../cost-estimate/group2-aws-cost-estimate.csv) and [JSON](../cost-estimate/group2-aws-cost-estimate.json) |
| Pricing team guide | [docs/cost-estimate/group2-aws-pricing-team-guide.docx](../cost-estimate/group2-aws-pricing-team-guide.docx) |
| Week 4 presentation | [docs/delivery/](./); Ema Sena may provide a new version. Confirm the final PPTX and add a matching PDF for review before submission |
| Application screenshots and demo evidence | Confirm existing locations or add evidence and record the exact paths here |
| Depreciation explanation | Straight-line calculation in [depreciation.py](../../backend/asset_api/depreciation.py), with examples in [test_depreciation.py](../../backend/tests/test_depreciation.py). Uses completed months and never reduces book value below salvage value; confirm the final presentation explanation |
| AI prompt and sample result | Prompts in [photo_analysis.py](../../backend/asset_api/photo_analysis.py) and [maintenance_ai.py](../../backend/asset_api/maintenance_ai.py). Simulated responses in [photo analysis tests](../../backend/tests/test_photo_analysis.py) and [maintenance AI tests](../../backend/tests/test_maintenance_ai.py); capture a real application result for demo evidence |
| Test results including security checks | Local backend unit-test result recorded below; includes authorization and AI-input filtering tests. Deployed application checks remain to be confirmed |
| Contribution summary | Confirm the required format and location with the team |
| Short project reflection | Confirm existing material; proposed path if needed: `docs/project-reflection.md` |
| Cleanup instructions | Confirm the existing instructions and their coverage of deployed resources |

The final estimate from the 4 October 2026 Calculator export is **USD 3.55 per month**, **USD 42.60 over 12 months** and **USD 0.00 upfront** (approximately USD 0.12 per day). It covers one assumed environment in us-east-1, including Amplify, X-Ray, planned EventBridge usage and SNS monitoring notifications. These are estimated charges under the documented workload assumptions, excluding taxes.

[AWS Pricing Calculator final estimate](https://calculator.aws/#/estimate?id=98808bdeb1af05aa13d820d3abe167b94a322e0a)

The export links use the repository filenames. Align the committed exports, cost document and slides with this final estimate before submission.

### Local backend test verification

- Verification date: 9 October 2026.
- Tested commit: `30b404ff863c430864e423d968c9126e88a0d636`; working tree was clean.
- Environment: local macOS, Python 3.14.2.
- Command: `python3 -m unittest discover -s backend/tests -v`.
- Result: 163 tests passed (`OK`).
- Scope: backend unit tests, including authorization, depreciation and AI response validation. AWS deployment, live Bedrock results and end-to-end application behavior were not verified by this run. The configured Lambda runtime is Python 3.11; this local run does not verify that runtime.

## 3 Remaining actions before submission

1. **Confirm the submission instructions.** Check the instructor's channel, deadline and required materials; agree who submits on behalf of Group 2.
2. **Confirm the deployed application.** Record the final URL, environment, deployed commit and verification date. Agree how long the application must remain available before cleanup.
3. **Complete the demonstration and evidence.** Verify login, role permissions, asset creation and updates, and the photo analysis workflow with human review. Include depreciation and lifecycle features required by the project brief. Record the environment, date and relevant test results alongside the evidence.
4. **Finalize the documentation and presentation.** Confirm that the architecture, AWS resources, cost estimate and slides describe the delivered implementation. Keep Week 3 as historical material and use one clearly named final Week 4 deck, with a matching PDF.
5. **Complete this index.** Replace the remaining confirmation entries with exact paths or links, record the submitted commit and have the team review the final materials.
6. **Check cleanup coverage.** Include resources created outside the SAM stack, such as Amplify and the SNS topic `smart-asset-tracker-alerts`. Schedule cleanup after the agreed review period.

Group 2 maintains this dated snapshot through final handoff. Track ongoing work in GitHub issues and refresh this index before submission.
