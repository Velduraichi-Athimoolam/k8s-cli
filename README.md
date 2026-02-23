cat > README.md << 'EOF'
# ☸️ k8s-cli

A lightweight Python CLI for interacting with Kubernetes clusters — including Amazon EKS.

## Features
- Get pods, deployments, services, nodes, configmaps, namespaces
- Describe pods, tail logs, delete pods
- Scale deployments, trigger rolling restarts
- Port-forward, exec into pods
- Apply/delete YAML manifests
- Multi-context / multi-cluster support

## Installation
```bash
git clone https://github.com/YOUR_USERNAME/k8s-cli.git
cd k8s-cli
pip install -r requirements.txt
```

## Usage
```bash
python k8s_cli.py --help
python k8s_cli.py get pods -n default
python k8s_cli.py get nodes
python k8s_cli.py logs my-pod --tail 100
python k8s_cli.py scale deployment my-app --replicas 3 -n production
python k8s_cli.py cluster-info
```

## EKS Setup
```bash
aws eks update-kubeconfig --region us-east-1 --name my-cluster
python k8s_cli.py get nodes
```

## Requirements
- Python 3.8+
- kubectl
- AWS CLI (for EKS)

## License
MIT
EOF
