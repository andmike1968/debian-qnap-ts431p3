// SPDX-License-Identifier: GPL-2.0
/*
 * External PCIe link 0 of the Annapurna Alpine SoC (QNAP TS-431P3), where the USB controller lives.
 * Reduced from drivers/pci/host/pci-external-alpine.c of the QNAP GPL sources (QTS 5.2.3, kernel 4.2).
 * U-Boot has already brought the link up (PBS pcie_conf_1 bit0, LTSSM L0): this driver only provides
 * the right config-space access (local bridge + ECAM with forced bus number), MSI and PCIe tuning.
 * Parameters:
 *   add_devices=0 (default): only list the devices found, do NOT hand them to drivers.
 *   add_devices=1          : hand them to drivers (xhci).
 *   dma32=1, nosnoop=1  : debugging switches, off by default (they did not fix the USB write errors).
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/pci.h>
#include <linux/of.h>
#include <linux/of_irq.h>
#include <linux/io.h>
#include <linux/irqdomain.h>
#include <linux/dma-mapping.h>

#define AL_REGS   0xfd800000UL	/* pcie-external0 controller registers */
#define AL_ECAM   0xfb600000UL	/* ECAM window (PBS ext_ecam0 = 0xfb603106) */
#define AL_PBS    0xfd8a8000UL
#define AXI_CFG_TARGET_BUS 0x40	/* rev2: axi.ob_ctrl.cfg_target_bus */
#define AXI_CFG_CONTROL    0x44	/* rev2: axi.ob_ctrl.cfg_control */
#define APP_DEBUG_INFO0    0x1080	/* rev2: app (0x1000) + debug (0x80) */
#define BRIDGE_CFG         0x2000	/* cfg-space-offset from the original DTB */

static int add_devices;
module_param(add_devices, int, 0444);
static int dma32 = 0;
module_param(dma32, int, 0444);
/* debug: clear the AXI snoop bits of the USB DMA (QTS enables CCU snoop, mainline does not) */
static int nosnoop = 0;
module_param(nosnoop, int, 0444);

static struct {
	void __iomem *regs, *ecam;
	u8 target;
	spinlock_t lock;
	int irq;
	struct resource mem, busn;
	struct platform_device *pdev;
	struct pci_host_bridge *bridge;
} A = {
	.mem  = { .name = "pcie-external0 mem", .start = 0xe0010000, .end = 0xe7ffffff, .flags = IORESOURCE_MEM },
	.busn = { .name = "pcie-external0 bus", .start = 0, .end = 0xff, .flags = IORESOURCE_BUS },
};

static void __iomem *al_cfg_addr(struct pci_bus *bus, unsigned int devfn, int where)
{
	if (bus->number == 0)
		return devfn ? NULL : A.regs + BRIDGE_CFG + where;
	if (PCI_SLOT(devfn))		/* only one device behind the root port */
		return NULL;
	if (bus->number != A.target) {
		u32 r = readl(A.regs + AXI_CFG_TARGET_BUS);
		r = (r & ~0xffffu) | (bus->number << 8) | 0xff;
		writel(r, A.regs + AXI_CFG_TARGET_BUS);
		A.target = bus->number;
	}
	return A.ecam + (PCI_FUNC(devfn) << 12) + where;
}

static int al_read(struct pci_bus *bus, unsigned int devfn, int where, int size, u32 *val)
{
	unsigned long f; void __iomem *a; int rc = PCIBIOS_SUCCESSFUL; u32 v = ~0;
	spin_lock_irqsave(&A.lock, f);
	a = al_cfg_addr(bus, devfn, where);
	if (!a) rc = PCIBIOS_DEVICE_NOT_FOUND;
	else if (size == 1) v = readb(a);
	else if (size == 2) v = readw(a);
	else v = readl(a);
	spin_unlock_irqrestore(&A.lock, f);
	*val = v;
	return rc;
}

static int al_write(struct pci_bus *bus, unsigned int devfn, int where, int size, u32 val)
{
	unsigned long f; void __iomem *a; int rc = PCIBIOS_SUCCESSFUL;
	spin_lock_irqsave(&A.lock, f);
	a = al_cfg_addr(bus, devfn, where);
	if (!a) rc = PCIBIOS_DEVICE_NOT_FOUND;
	else if (size == 1) writeb(val, a);
	else if (size == 2) writew(val, a);
	else writel(val, a);
	spin_unlock_irqrestore(&A.lock, f);
	return rc;
}

static struct pci_ops al_ops = { .read = al_read, .write = al_write };

static int al_map_irq(const struct pci_dev *d, u8 slot, u8 pin) { return A.irq; }

static int __init al_init(void)
{
	void __iomem *pbs;
	struct device_node *gic;
	struct of_phandle_args ia = { .args_count = 3, .args = { 0, 45, 4 } }; /* GIC SPI 45, level high */
	u32 conf1, info0, ltssm;
	struct pci_bus *bus;
	int rc;

	pbs = ioremap(AL_PBS, 0x1000);
	A.regs = ioremap(AL_REGS, 0x20000);
	if (!pbs || !A.regs) return -ENOMEM;
	conf1 = readl(pbs + 0xe4);
	iounmap(pbs);
	info0 = readl(A.regs + APP_DEBUG_INFO0);
	ltssm = (info0 >> 3) & 0x3f;
	pr_info("al_ext_pcie: pcie_conf_1=0x%x LTSSM=0x%x\n", conf1, ltssm);
	if (!(conf1 & 1) || (ltssm != 0x11 && ltssm != 0x12)) {
		pr_err("al_ext_pcie: link not up, giving up\n");
		rc = -ENODEV; goto err_regs;
	}
	{	/* axi.ctrl.master_arctl 0x14 / master_awctl 0x18: bit26 OVR_SNOOP, bit27 SNOOP */
		u32 ar = readl(A.regs + 0x14), aw = readl(A.regs + 0x18);
		if (nosnoop) {
			writel((ar | BIT(26)) & ~BIT(27), A.regs + 0x14);
			writel((aw | BIT(26)) & ~BIT(27), A.regs + 0x18);
		}
		pr_info("al_ext_pcie: snoop arctl 0x%x->0x%x awctl 0x%x->0x%x (nosnoop=%d)\n",
			ar, readl(A.regs + 0x14), aw, readl(A.regs + 0x18), nosnoop);
	}
	A.ecam = ioremap(AL_ECAM, 0x100000);
	if (!A.ecam) { rc = -ENOMEM; goto err_regs; }
	spin_lock_init(&A.lock);
	/* as al_pcie_cfg_prepare: secondary bus 1, subordinate 0xff, target bus 1 */
	writel((readl(A.regs + AXI_CFG_CONTROL) & ~0x00ffff00u) | (1 << 16) | (0xff << 8), A.regs + AXI_CFG_CONTROL);
	writel((readl(A.regs + AXI_CFG_TARGET_BUS) & ~0xffffu) | (1 << 8) | 0xff, A.regs + AXI_CFG_TARGET_BUS);
	A.target = 1;

	gic = of_find_compatible_node(NULL, NULL, "arm,cortex-a15-gic");
	ia.np = gic;
	A.irq = gic ? irq_create_of_mapping(&ia) : 0;
	of_node_put(gic);
	pr_info("al_ext_pcie: irq %d\n", A.irq);

	rc = request_resource(&iomem_resource, &A.mem);
	if (rc) { pr_err("al_ext_pcie: memory window busy\n"); goto err_ecam; }

	A.pdev = platform_device_register_simple("al-ext-pcie0", -1, NULL, 0);
	if (IS_ERR(A.pdev)) { rc = PTR_ERR(A.pdev); goto err_mem; }
	A.bridge = pci_alloc_host_bridge(0);
	if (!A.bridge) { rc = -ENOMEM; goto err_pdev; }
	A.bridge->dev.parent = &A.pdev->dev;
	A.bridge->sysdata = &A;
	A.bridge->ops = &al_ops;
	A.bridge->busnr = 0;
	A.bridge->domain_nr = 1;
	A.bridge->map_irq = al_map_irq;
	A.bridge->swizzle_irq = pci_common_swizzle;
	{	/* interrupts via MSI through the al,alpine-msix domain (as QTS: msi-parent); INTx never reaches the CPU */
		struct device_node *mx = of_find_compatible_node(NULL, NULL, "al,alpine-msix");
		struct irq_domain *d = mx ? irq_find_matching_fwnode(of_node_to_fwnode(mx), DOMAIN_BUS_PCI_MSI) : NULL;
		of_node_put(mx);
		pr_info("al_ext_pcie: MSI domain %s\n", d ? d->name : "NOT found");
		if (d)
			dev_set_msi_domain(&A.bridge->dev, d);
	}
	pci_add_resource(&A.bridge->windows, &A.mem);
	pci_add_resource(&A.bridge->windows, &A.busn);

	pr_info("al_ext_pcie: scanning bus (add_devices=%d)\n", add_devices);
	rc = pci_scan_root_bus_bridge(A.bridge);
	if (rc) { pr_err("al_ext_pcie: scan failed %d\n", rc); pci_free_host_bridge(A.bridge); A.bridge = NULL; goto err_pdev; }
	bus = A.bridge->bus;
	pci_bus_size_bridges(bus);
	pci_bus_assign_resources(bus);
	{
		struct pci_dev *d = NULL;
		for_each_pci_dev(d)
			if (pci_domain_nr(d->bus) == 1)
			{
				pr_info("al_ext_pcie: found %s %04x:%04x class %06x BAR0 %pR\n",
					pci_name(d), d->vendor, d->device, d->class, &d->resource[0]);
				/* debug: USB DMA below 4 GB only (dma32=1) */
				if (dma32) {
					d->dev.bus_dma_limit = DMA_BIT_MASK(32);
					pr_info("al_ext_pcie: %s DMA limited to 32 bit\n", pci_name(d));
				}
			}
	}
	{	/* ROOT CAUSE of the USB write errors. The root port accepts read requests up to 256 B and
		 * no Extended Tags; the Etron controller asked for 512 B with ExtTag -> "TRB error" on writes.
		 * Force MRRS 128 B and ExtTag off on the whole domain, before handing it to the drivers. */
		struct pci_dev *d = NULL;
		for_each_pci_dev(d)
			if (pci_domain_nr(d->bus) == 1 && pci_is_pcie(d)) {
				pcie_capability_clear_word(d, PCI_EXP_DEVCTL, PCI_EXP_DEVCTL_EXT_TAG);
				pcie_set_readrq(d, 128);
				pr_info("al_ext_pcie: %s MRRS %d, ExtTag off\n", pci_name(d), pcie_get_readrq(d));
			}
	}
	if (add_devices) {
		pci_bus_add_devices(bus);
		pr_info("al_ext_pcie: devices handed to drivers\n");
	}
	return 0;

err_pdev:
	platform_device_unregister(A.pdev);
err_mem:
	release_resource(&A.mem);
err_ecam:
	iounmap(A.ecam);
err_regs:
	iounmap(A.regs);
	return rc;
}

static void __exit al_exit(void)
{
	if (A.bridge) {
		pci_lock_rescan_remove();
		pci_stop_root_bus(A.bridge->bus);
		pci_remove_root_bus(A.bridge->bus);
		pci_unlock_rescan_remove();
	}
	platform_device_unregister(A.pdev);
	release_resource(&A.mem);
	iounmap(A.ecam);
	iounmap(A.regs);
}

module_init(al_init);
module_exit(al_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Alpine pcie-external0 (USB) for QNAP TS-431P3, from QNAP GPL sources");
