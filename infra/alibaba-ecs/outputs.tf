output "region" {
  value = var.region
}

output "ecs_instance_id" {
  value = alicloud_instance.judging.id
}

output "ecs_public_ip" {
  value = alicloud_instance.judging.public_ip
}

output "security_group_id" {
  value = alicloud_security_group.judging.id
}

output "allowed_public_ports" {
  value = ["80/tcp", "443/tcp"]
}

output "restricted_ssh_source_cidr" {
  value = var.ssh_source_cidr
}

output "post_provisioning_steps" {
  value = <<-EOT
    1. Install Docker Engine and Caddy on the ECS VM.
    2. Create /opt/apps/platform, /opt/apps/yiting, and /opt/apps/backups.
    3. Create root-owned secret directories under /opt/apps/yiting/secrets.
    4. Start the platform and yiting Compose projects.
    5. Fill the README parity table with actual ECS console values before submitting proof.
  EOT
}
