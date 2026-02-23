#!/usr/bin/env python3
"""
k8s-cli: A Python CLI for Kubernetes API interaction
Usage: python k8s_cli.py [command] [options]
"""

import argparse
import json
import os
import sys
import subprocess
from typing import Optional

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    HAS_K8S = True
except ImportError:
    HAS_K8S = False

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

# ── Color helpers ────────────────────────────────────────────────────────────

class Colors:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def ok(msg):    print(f"{Colors.GREEN}✔ {msg}{Colors.RESET}")
def err(msg):   print(f"{Colors.RED}✖ {msg}{Colors.RESET}", file=sys.stderr)
def warn(msg):  print(f"{Colors.YELLOW}⚠ {msg}{Colors.RESET}")
def info(msg):  print(f"{Colors.BLUE}ℹ {msg}{Colors.RESET}")
def header(msg):print(f"{Colors.BOLD}{msg}{Colors.RESET}")

# ── Kubernetes client setup ──────────────────────────────────────────────────

def load_kube_config(context: Optional[str] = None, in_cluster: bool = False):
    if not HAS_K8S:
        err("kubernetes package not installed. Run: pip install kubernetes")
        sys.exit(1)
    try:
        if in_cluster:
            config.load_incluster_config()
            ok("Loaded in-cluster config")
        else:
            config.load_kube_config(context=context)
            ctx = context or "default"
            ok(f"Loaded kubeconfig (context: {ctx})")
    except Exception as e:
        err(f"Failed to load config: {e}")
        sys.exit(1)

# ── Table rendering ──────────────────────────────────────────────────────────

def print_table(headers, rows, fmt="grid"):
    if HAS_TABULATE:
        print(tabulate(rows, headers=headers, tablefmt=fmt))
    else:
        # Fallback: fixed-width manual table
        col_w = [max(len(str(headers[i])), max((len(str(r[i])) for r in rows), default=0))
                 for i in range(len(headers))]
        sep = "  ".join("-" * w for w in col_w)
        fmt_row = lambda r: "  ".join(str(r[i]).ljust(col_w[i]) for i in range(len(r)))
        print(fmt_row(headers))
        print(sep)
        for row in rows:
            print(fmt_row(row))

# ── Namespace commands ───────────────────────────────────────────────────────

def cmd_get_namespaces(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    try:
        nss = v1.list_namespace()
        rows = [(ns.metadata.name, ns.status.phase) for ns in nss.items]
        header("Namespaces")
        print_table(["NAME", "STATUS"], rows)
    except ApiException as e:
        err(f"API error: {e.reason}")

# ── Pod commands ─────────────────────────────────────────────────────────────

def cmd_get_pods(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    ns = args.namespace or "default"
    try:
        pods = v1.list_namespaced_pod(namespace=ns)
        rows = []
        for p in pods.items:
            ready = sum(1 for cs in (p.status.container_statuses or []) if cs.ready)
            total = len(p.spec.containers)
            restarts = sum(cs.restart_count for cs in (p.status.container_statuses or []))
            rows.append((
                p.metadata.name,
                f"{ready}/{total}",
                p.status.phase or "Unknown",
                restarts,
                p.metadata.namespace,
            ))
        header(f"Pods in namespace: {ns}")
        print_table(["NAME", "READY", "STATUS", "RESTARTS", "NAMESPACE"], rows)
    except ApiException as e:
        err(f"API error: {e.reason}")

def cmd_describe_pod(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    ns = args.namespace or "default"
    try:
        pod = v1.read_namespaced_pod(name=args.name, namespace=ns)
        header(f"Pod: {pod.metadata.name}")
        print(f"  Namespace : {pod.metadata.namespace}")
        print(f"  Node      : {pod.spec.node_name}")
        print(f"  Phase     : {pod.status.phase}")
        print(f"  IP        : {pod.status.pod_ip}")
        print(f"  Created   : {pod.metadata.creation_timestamp}")
        print(f"\n  {'Containers':}")
        for c in pod.spec.containers:
            print(f"    - {c.name}  image={c.image}")
        if pod.status.container_statuses:
            print(f"\n  {'Container Status':}")
            for cs in pod.status.container_statuses:
                state = list(cs.state.to_dict().keys())[0] if cs.state else "unknown"
                print(f"    - {cs.name}  ready={cs.ready}  restarts={cs.restart_count}  state={state}")
        if args.output == "json":
            print(json.dumps(pod.to_dict(), indent=2, default=str))
    except ApiException as e:
        err(f"API error: {e.reason}")

def cmd_pod_logs(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    ns = args.namespace or "default"
    try:
        logs = v1.read_namespaced_pod_log(
            name=args.name,
            namespace=ns,
            container=args.container,
            tail_lines=args.tail,
            previous=args.previous,
        )
        print(logs)
    except ApiException as e:
        err(f"API error: {e.reason}")

def cmd_delete_pod(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    ns = args.namespace or "default"
    try:
        v1.delete_namespaced_pod(name=args.name, namespace=ns)
        ok(f"Pod '{args.name}' deleted from namespace '{ns}'")
    except ApiException as e:
        err(f"API error: {e.reason}")

# ── Deployment commands ──────────────────────────────────────────────────────

def cmd_get_deployments(args):
    load_kube_config(args.context, args.in_cluster)
    apps = client.AppsV1Api()
    ns = args.namespace or "default"
    try:
        deps = apps.list_namespaced_deployment(namespace=ns)
        rows = [
            (
                d.metadata.name,
                d.status.ready_replicas or 0,
                d.status.replicas or 0,
                d.status.updated_replicas or 0,
                d.status.available_replicas or 0,
            )
            for d in deps.items
        ]
        header(f"Deployments in namespace: {ns}")
        print_table(["NAME", "READY", "DESIRED", "UPDATED", "AVAILABLE"], rows)
    except ApiException as e:
        err(f"API error: {e.reason}")

def cmd_scale_deployment(args):
    load_kube_config(args.context, args.in_cluster)
    apps = client.AppsV1Api()
    ns = args.namespace or "default"
    try:
        dep = apps.read_namespaced_deployment(name=args.name, namespace=ns)
        dep.spec.replicas = args.replicas
        apps.patch_namespaced_deployment(name=args.name, namespace=ns, body=dep)
        ok(f"Deployment '{args.name}' scaled to {args.replicas} replicas")
    except ApiException as e:
        err(f"API error: {e.reason}")

def cmd_rollout_restart(args):
    load_kube_config(args.context, args.in_cluster)
    apps = client.AppsV1Api()
    ns = args.namespace or "default"
    import datetime
    try:
        dep = apps.read_namespaced_deployment(name=args.name, namespace=ns)
        if not dep.spec.template.metadata.annotations:
            dep.spec.template.metadata.annotations = {}
        dep.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = \
            datetime.datetime.utcnow().isoformat() + "Z"
        apps.patch_namespaced_deployment(name=args.name, namespace=ns, body=dep)
        ok(f"Rollout restart triggered for deployment '{args.name}'")
    except ApiException as e:
        err(f"API error: {e.reason}")

# ── Service commands ─────────────────────────────────────────────────────────

def cmd_get_services(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    ns = args.namespace or "default"
    try:
        svcs = v1.list_namespaced_service(namespace=ns)
        rows = []
        for s in svcs.items:
            ports = ", ".join(
                f"{p.port}:{p.node_port or '-'}/{p.protocol}"
                for p in (s.spec.ports or [])
            )
            rows.append((s.metadata.name, s.spec.type, s.spec.cluster_ip, ports))
        header(f"Services in namespace: {ns}")
        print_table(["NAME", "TYPE", "CLUSTER-IP", "PORTS"], rows)
    except ApiException as e:
        err(f"API error: {e.reason}")

# ── ConfigMap commands ───────────────────────────────────────────────────────

def cmd_get_configmaps(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    ns = args.namespace or "default"
    try:
        cms = v1.list_namespaced_config_map(namespace=ns)
        rows = [(cm.metadata.name, len(cm.data or {}), cm.metadata.creation_timestamp)
                for cm in cms.items]
        header(f"ConfigMaps in namespace: {ns}")
        print_table(["NAME", "DATA", "CREATED"], rows)
    except ApiException as e:
        err(f"API error: {e.reason}")

# ── Node commands ─────────────────────────────────────────────────────────────

def cmd_get_nodes(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    try:
        nodes = v1.list_node()
        rows = []
        for n in nodes.items:
            conds = {c.type: c.status for c in (n.status.conditions or [])}
            ready = "True" if conds.get("Ready") == "True" else "False"
            roles = [l.split("/")[-1] for l in n.metadata.labels if "node-role.kubernetes.io/" in l]
            ver = n.status.node_info.kubelet_version
            rows.append((n.metadata.name, ready, ",".join(roles) or "<none>", ver))
        header("Nodes")
        print_table(["NAME", "READY", "ROLES", "VERSION"], rows)
    except ApiException as e:
        err(f"API error: {e.reason}")

# ── Cluster info ─────────────────────────────────────────────────────────────

def cmd_cluster_info(args):
    load_kube_config(args.context, args.in_cluster)
    v1 = client.CoreV1Api()
    apps = client.AppsV1Api()
    try:
        nss   = len(v1.list_namespace().items)
        nodes = len(v1.list_node().items)
        ns = args.namespace or "default"
        pods  = len(v1.list_namespaced_pod(namespace=ns).items)
        deps  = len(apps.list_namespaced_deployment(namespace=ns).items)
        svcs  = len(v1.list_namespaced_service(namespace=ns).items)
        header("Cluster Summary")
        print_table(
            ["Resource", "Count"],
            [
                ("Namespaces",  nss),
                ("Nodes",       nodes),
                (f"Pods ({ns})",        pods),
                (f"Deployments ({ns})", deps),
                (f"Services ({ns})",    svcs),
            ]
        )
    except ApiException as e:
        err(f"API error: {e.reason}")

# ── Context commands ──────────────────────────────────────────────────────────

def cmd_get_contexts(args):
    if not HAS_K8S:
        err("kubernetes package not installed.")
        sys.exit(1)
    try:
        contexts, active = config.list_kube_config_contexts()
        rows = []
        for ctx in contexts:
            name = ctx["name"]
            cluster = ctx["context"].get("cluster", "")
            user    = ctx["context"].get("user", "")
            current = "✔" if ctx["name"] == active["name"] else ""
            rows.append((current, name, cluster, user))
        header("Contexts")
        print_table(["CURRENT", "NAME", "CLUSTER", "USER"], rows)
    except Exception as e:
        err(f"Error: {e}")

def cmd_use_context(args):
    if not HAS_K8S:
        err("kubernetes package not installed.")
        sys.exit(1)
    try:
        config.load_kube_config(context=args.name)
        ok(f"Switched to context '{args.name}'")
    except Exception as e:
        err(f"Error: {e}")

# ── Exec / Port-forward (wraps kubectl) ──────────────────────────────────────

def cmd_exec(args):
    ns = args.namespace or "default"
    cmd = ["kubectl", "exec", "-it", args.name, "-n", ns]
    if args.container:
        cmd += ["-c", args.container]
    cmd += ["--"] + args.cmd
    info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd)

def cmd_port_forward(args):
    ns = args.namespace or "default"
    cmd = ["kubectl", "port-forward", args.name, args.ports, "-n", ns]
    info(f"Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        ok("Port-forward stopped.")

# ── Apply / Delete manifest ───────────────────────────────────────────────────

def cmd_apply(args):
    cmd = ["kubectl", "apply", "-f", args.file]
    info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd)

def cmd_delete_resource(args):
    cmd = ["kubectl", "delete", "-f", args.file]
    if args.force:
        cmd.append("--force")
    info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd)

# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="k8s-cli",
        description="🚀 Kubernetes CLI — interact with your cluster via Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python k8s_cli.py get namespaces
  python k8s_cli.py get pods -n kube-system
  python k8s_cli.py describe pod my-pod -n default
  python k8s_cli.py logs my-pod -n default --tail 50
  python k8s_cli.py scale deployment my-deploy -n default --replicas 3
  python k8s_cli.py rollout restart my-deploy -n default
  python k8s_cli.py get services -n default
  python k8s_cli.py get nodes
  python k8s_cli.py cluster-info
  python k8s_cli.py get contexts
  python k8s_cli.py exec my-pod -n default -- /bin/sh
  python k8s_cli.py port-forward my-pod 8080:80 -n default
  python k8s_cli.py apply -f deployment.yaml
        """
    )

    # Global flags
    parser.add_argument("--context",    default=None,  help="Kubeconfig context to use")
    parser.add_argument("--in-cluster", action="store_true", help="Use in-cluster config")
    parser.add_argument("-n", "--namespace", default=None, help="Kubernetes namespace")
    parser.add_argument("-o", "--output", default="table", choices=["table", "json"], help="Output format")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ── get ──
    get_p = sub.add_parser("get", help="Get resources")
    get_sub = get_p.add_subparsers(dest="resource", metavar="RESOURCE")

    get_sub.add_parser("namespaces",  help="List namespaces")
    get_sub.add_parser("pods",        help="List pods")
    get_sub.add_parser("deployments", help="List deployments")
    get_sub.add_parser("services",    help="List services")
    get_sub.add_parser("configmaps",  help="List configmaps")
    get_sub.add_parser("nodes",       help="List nodes")
    get_sub.add_parser("contexts",    help="List kubeconfig contexts")

    # ── describe ──
    desc_p = sub.add_parser("describe", help="Describe a resource")
    desc_sub = desc_p.add_subparsers(dest="resource", metavar="RESOURCE")
    pod_desc = desc_sub.add_parser("pod", help="Describe a pod")
    pod_desc.add_argument("name", help="Pod name")

    # ── logs ──
    logs_p = sub.add_parser("logs", help="Get pod logs")
    logs_p.add_argument("name", help="Pod name")
    logs_p.add_argument("-c", "--container", default=None, help="Container name")
    logs_p.add_argument("--tail", type=int, default=100, help="Lines to tail (default 100)")
    logs_p.add_argument("--previous", action="store_true", help="Show logs from previous container")

    # ── delete pod ──
    del_pod_p = sub.add_parser("delete-pod", help="Delete a pod")
    del_pod_p.add_argument("name", help="Pod name")

    # ── scale ──
    scale_p = sub.add_parser("scale", help="Scale a deployment")
    scale_sub = scale_p.add_subparsers(dest="resource")
    dep_scale = scale_sub.add_parser("deployment", help="Scale deployment")
    dep_scale.add_argument("name", help="Deployment name")
    dep_scale.add_argument("--replicas", type=int, required=True, help="Number of replicas")

    # ── rollout ──
    roll_p = sub.add_parser("rollout", help="Rollout operations")
    roll_sub = roll_p.add_subparsers(dest="action")
    restart = roll_sub.add_parser("restart", help="Restart a deployment")
    restart.add_argument("name", help="Deployment name")

    # ── cluster-info ──
    sub.add_parser("cluster-info", help="Show cluster summary")

    # ── use-context ──
    uc = sub.add_parser("use-context", help="Switch kubeconfig context")
    uc.add_argument("name", help="Context name")

    # ── exec ──
    exec_p = sub.add_parser("exec", help="Execute command in a pod (wraps kubectl)")
    exec_p.add_argument("name", help="Pod name")
    exec_p.add_argument("-c", "--container", default=None, help="Container name")
    exec_p.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run")

    # ── port-forward ──
    pf = sub.add_parser("port-forward", help="Forward local port to pod (wraps kubectl)")
    pf.add_argument("name", help="Pod name or service/deploy (e.g. pod/name)")
    pf.add_argument("ports", help="Port mapping e.g. 8080:80")

    # ── apply ──
    apply_p = sub.add_parser("apply", help="Apply a YAML manifest (wraps kubectl)")
    apply_p.add_argument("-f", "--file", required=True, help="Path to manifest file")

    # ── delete (manifest) ──
    del_p = sub.add_parser("delete", help="Delete resources from a YAML manifest")
    del_p.add_argument("-f", "--file", required=True, help="Path to manifest file")
    del_p.add_argument("--force", action="store_true", help="Force deletion")

    return parser

# ── Main dispatch ─────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # get <resource>
    if args.command == "get":
        if args.resource == "namespaces":  cmd_get_namespaces(args)
        elif args.resource == "pods":      cmd_get_pods(args)
        elif args.resource == "deployments": cmd_get_deployments(args)
        elif args.resource == "services":  cmd_get_services(args)
        elif args.resource == "configmaps": cmd_get_configmaps(args)
        elif args.resource == "nodes":     cmd_get_nodes(args)
        elif args.resource == "contexts":  cmd_get_contexts(args)
        else:
            err(f"Unknown resource '{args.resource}'")
            parser.print_help()

    elif args.command == "describe":
        if args.resource == "pod":   cmd_describe_pod(args)
        else:
            err(f"Unknown resource '{args.resource}'")

    elif args.command == "logs":       cmd_pod_logs(args)
    elif args.command == "delete-pod": cmd_delete_pod(args)

    elif args.command == "scale":
        if args.resource == "deployment": cmd_scale_deployment(args)
        else:
            err(f"Unknown resource '{args.resource}'")

    elif args.command == "rollout":
        if args.action == "restart": cmd_rollout_restart(args)

    elif args.command == "cluster-info": cmd_cluster_info(args)
    elif args.command == "use-context":  cmd_use_context(args)
    elif args.command == "exec":         cmd_exec(args)
    elif args.command == "port-forward": cmd_port_forward(args)
    elif args.command == "apply":        cmd_apply(args)
    elif args.command == "delete":       cmd_delete_resource(args)
    else:
        err(f"Unknown command '{args.command}'")
        parser.print_help()


if __name__ == "__main__":
    main()
