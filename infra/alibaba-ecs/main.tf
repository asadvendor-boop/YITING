provider "alicloud" {
  region = var.region
}

locals {
  name = var.name_prefix
}

data "alicloud_zones" "available" {
  available_instance_type = var.ecs_instance_type
  available_disk_category = "cloud_essd"
}

data "alicloud_images" "ubuntu" {
  owners      = "system"
  name_regex  = "^ubuntu_24_04_x64"
  most_recent = true
}

resource "alicloud_vpc" "judging" {
  vpc_name   = "${local.name}-vpc"
  cidr_block = "10.74.0.0/16"
  tags       = var.tags
}

resource "alicloud_vswitch" "judging" {
  vpc_id       = alicloud_vpc.judging.id
  zone_id      = data.alicloud_zones.available.zones[0].id
  cidr_block   = "10.74.1.0/24"
  vswitch_name = "${local.name}-vsw"
  tags         = var.tags
}

resource "alicloud_security_group" "judging" {
  security_group_name = "${local.name}-sg"
  description         = "Caddy HTTPS plus restricted SSH for the shared YITING judging VM"
  vpc_id              = alicloud_vpc.judging.id
  tags                = var.tags
}

resource "alicloud_security_group_rule" "ssh" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "22/22"
  priority          = 10
  security_group_id = alicloud_security_group.judging.id
  cidr_ip           = var.ssh_source_cidr
  description       = "Key-only SSH from the operator IP range"
}

resource "alicloud_security_group_rule" "http" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "80/80"
  priority          = 20
  security_group_id = alicloud_security_group.judging.id
  cidr_ip           = "0.0.0.0/0"
  description       = "Caddy HTTP challenge and redirect"
}

resource "alicloud_security_group_rule" "https" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "443/443"
  priority          = 30
  security_group_id = alicloud_security_group.judging.id
  cidr_ip           = "0.0.0.0/0"
  description       = "Caddy HTTPS ingress"
}

resource "alicloud_instance" "judging" {
  instance_name              = "${local.name}-ecs"
  host_name                  = "qwen-hackathon-judging"
  image_id                   = data.alicloud_images.ubuntu.images[0].id
  instance_type              = var.ecs_instance_type
  security_groups            = [alicloud_security_group.judging.id]
  vswitch_id                 = alicloud_vswitch.judging.id
  key_name                   = var.ssh_key_pair_name
  internet_charge_type       = "PayByTraffic"
  internet_max_bandwidth_out = var.public_bandwidth_mbps
  system_disk_category       = "cloud_essd"
  system_disk_size           = var.system_disk_size_gb
  tags                       = var.tags
}
