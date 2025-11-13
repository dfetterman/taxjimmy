#!/bin/bash

# Function to select VPC
select_vpc() {
    # Print header to stderr
    echo "Available VPCs:" >&2
    
    # Get VPC data including CIDR blocks
    vpc_data=$(aws ec2 describe-vpcs \
        --query 'Vpcs[].[VpcId,Tags[?Key==`Name`].Value|[0],CidrBlock]' \
        --output text)
    
    # Create array of VPC options
    IFS=$'\n' read -r -d '' -a vpc_options <<< "$vpc_data"
    
    # Show options on stderr
    for i in "${!vpc_options[@]}"; do
        echo "$((i+1))) ${vpc_options[$i]}" >&2
    done
    
    # Read selection from stdin
    read -p "Select VPC (1-${#vpc_options[@]}): " selection >&2
    
    if [[ $selection =~ ^[0-9]+$ ]] && [ "$selection" -ge 1 ] && [ "$selection" -le "${#vpc_options[@]}" ]; then
        selected_line=${vpc_options[$((selection-1))]}
        # Extract just the VPC ID and CIDR
        vpc_id=$(echo "$selected_line" | awk '{print $1}')
        vpc_cidr=$(echo "$selected_line" | awk '{print $NF}')  # Get the last field which should be CIDR
        
        # Show selection info on stderr
        echo "Selected VPC: $selected_line" >&2
        echo "Debug: Extracted VPC ID: $vpc_id" >&2
        echo "Debug: Extracted CIDR: $vpc_cidr" >&2
        
        # Return VPC ID and CIDR
        echo "$vpc_id $vpc_cidr"
        return 0
    else
        echo "Invalid selection" >&2
        return 1
    fi
}

# Function to select subnets
select_subnets() {
    local vpc_id=$1
    echo "Looking up subnets for VPC: $vpc_id" >&2
    
    # Get raw subnet data
    subnet_data=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$vpc_id" \
        --output text \
        --query 'Subnets[].[SubnetId,CidrBlock,AvailabilityZone,Tags[?Key==`Name`].Value|[0]]')
    
    if [ -z "$subnet_data" ]; then
        echo "No subnets found" >&2
        return 1
    fi
    
    # Convert subnet data to array
    IFS=$'\n' read -r -d '' -a subnet_options <<< "$subnet_data"
    
    # Show available subnets
    echo "Available subnets:" >&2
    for i in "${!subnet_options[@]}"; do
        echo "$((i+1))) ${subnet_options[$i]}" >&2
    done
    
    # Select first subnet
    echo "Select first subnet for RDS (PRIVATE subnet recommended):" >&2
    read -p "Select subnet (1-${#subnet_options[@]}): " selection1 >&2
    
    if ! [[ $selection1 =~ ^[0-9]+$ ]] || [ "$selection1" -lt 1 ] || [ "$selection1" -gt "${#subnet_options[@]}" ]; then
        echo "Invalid selection" >&2
        return 1
    fi
    
    subnet1=$(echo "${subnet_options[$((selection1-1))]}" | awk '{print $1}')
    echo "Selected first subnet: ${subnet_options[$((selection1-1))]}" >&2
    
    # Select second subnet
    echo "Select second subnet for RDS (PRIVATE subnet recommended):" >&2
    read -p "Select subnet (1-${#subnet_options[@]}): " selection2 >&2
    
    if ! [[ $selection2 =~ ^[0-9]+$ ]] || [ "$selection2" -lt 1 ] || [ "$selection2" -gt "${#subnet_options[@]}" ]; then
        echo "Invalid selection" >&2
        return 1
    fi
    
    if [ "$selection1" -eq "$selection2" ]; then
        echo "Error: Cannot select the same subnet twice" >&2
        return 1
    fi
    
    subnet2=$(echo "${subnet_options[$((selection2-1))]}" | awk '{print $1}')
    echo "Selected second subnet: ${subnet_options[$((selection2-1))]}" >&2
    
    # Return the selected subnet IDs
    echo "$subnet1 $subnet2"
}

# Export the functions
export -f select_vpc
export -f select_subnets 