## Future Infra Direction

Long-term target: split infrastructure into separate Terraform layers with distinct lifecycle ownership.

Desired structure:

- `infra/terraform/foundation/`
- `infra/terraform/app/`

Planned ownership split:

- `foundation/` should provision long-lived shared Azure infrastructure from the ground up
- `app/` should provision the deployable application layer that can be replaced more frequently

Foundation scope should eventually include:

- resource group
- networking, if needed
- Azure Container Registry
- Log Analytics workspace
- Azure Container Apps environment
- Azure Cosmos DB account
- Azure Storage account
- Azure Bot / Teams bot-related Azure resources

App scope should eventually include:

- Container App
- app-specific Cosmos SQL database and containers
- Azure Storage queue(s)
- app secrets/config wiring

Design goals for the future implementation:

- full ground-up provisioning, not reliance on pre-provisioned shared resources
- clean separation between slow-moving platform infrastructure and fast-moving app infrastructure
- `terraform destroy` on the app layer should not destroy the foundation layer
- periodic full environment bootstrap should still be possible from Terraform

Azure Bot note:

- If/when implemented, prefer provisioning Azure Bot resources through Terraform using `azapi` if needed rather than assuming first-class `azurerm` coverage is sufficient.
- Plan for single-tenant or managed-identity-style bot configuration rather than old multi-tenant bot assumptions.

Identity / Entra note:

- Do not assume the Microsoft Entra app registration can be fully Terraform-managed.
- If Graph API permissions are IT-approved on an existing app registration, foundation Terraform should support consuming an existing Entra app/client ID rather than trying to recreate that identity.
- In other words: aim for full Azure infrastructure provisioning, but allow identity integration with pre-approved tenant-managed app registrations where required by IT policy.

Not implementing this yet. Current Terraform remains a single app-layer-oriented module in `infra/terraform/container-app/`.
