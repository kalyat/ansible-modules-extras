#!/usr/bin/python
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.    If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
module: elb_application_lb_facts
short_description: Gather facts about EC2 Application Load Balancers in AWS
description:
  - Gather facts about EC2 Application Load Balancers in AWS
version_added: "1.0"
author:
  - "Sreejith Kalyat (github.com/kalyat)"
  - "Michael Schultz (github.com/mjschultz)"
  - "Fernando Jose Pando (@nand0p)"
options:
    names:
        description:
            - List of ALB names to gather facts about. Pass this option to gather facts about a set of ALBs, otherwise, all ALBs are returned.
        required: false
        default: null
        aliases: ['elb_ids', 'ec2_elbs']
extends_documentation_fragment:
        - aws
        - ec2
'''

EXAMPLES = '''
# Note: These examples do not set authentication details, see the AWS Guide for details.
# Output format tries to match ec2_elb_lb module input parameters

# Gather facts about all ALBs
- action:
        module: elb_application_lb_facts
    register: elb_facts

- action:
        module: debug
        msg: "{{ item.dns_name }}"
    with_items: "{{ elb_facts.elbs }}"

# Gather facts about a particular ALB
- action:
        module: elb_application_lb_facts
        names: frontend-prod-elb
    register: elb_facts

- action:
        module: debug
        msg: "{{ elb_facts.elbs.0.dns_name }}"

# Gather facts about a set of ALBs
- action:
        module: elb_application_lb_facts
        names:
        - frontend-prod-elb
        - backend-prod-elb
    register: elb_facts

- action:
        module: debug
        msg: "{{ item.dns_name }}"
    with_items: "{{ elb_facts.elbs }}"
'''

try:
    import boto3
    from boto.exception import BotoServerError
    import q
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

class ElbInformation(object):
    """ Handles ALB information """

    def __init__(self,
                 module,
                 names,
                 region,
                 **aws_connect_params):

        self.module = module
        self.names = names
        self.region = region
        self.aws_connect_params = aws_connect_params
        self.ec2, self.elbv2 = self._get_elb_connection(module)

    def _get_elb_connection(self, module):
        try:
            region, ec2_url, aws_connect_kwargs = get_aws_connection_info(module, boto3=True)
            if not region:
                self.module.fail_json(msg="Region must be specified as a parameter, in EC2_REGION or AWS_REGION environment variables or in boto configuration file")
            ec2 = boto3_conn(module, conn_type='client', resource='ec2', region=region, endpoint=ec2_url, **aws_connect_kwargs)
            elbv2 = boto3_conn(module, conn_type='client', resource='elbv2', region=region, endpoint=ec2_url, **aws_connect_kwargs)
        except ClientError as e:
            module.fail_json(msg=e.message)
        return ec2, elbv2

    def _get_zone_info(self, zones):
        zone_list = []
        for zone in zones:
            zone_dict = {
                'subnetid': zone['SubnetId'],
                'zonename': zone['ZoneName']
            }
            zone_list.append(zone_dict)
        return zone_list

    def _get_listeners(self, loadbalancerarns):
        listener_arns= []
        listener_list= []
        try:
            listeners = self.elbv2.describe_listeners(LoadBalancerArn=loadbalancerarns)
        except BotoServerError as err:
            self.module.fail_json(msg = "%s: %s" % (err.error_code, err.error_message))

        for listener in listeners['Listeners']:
            listener_arns.append(listener['ListenerArn']) 

        for arn in listener_arns:
            try:
                listener_data = self.elbv2.describe_listeners(ListenerArns=[arn])
            except BotoServerError as err:
                self.module.fail_json(msg = "%s: %s" % (err.error_code, err.error_message))
            for listener in listener_data['Listeners']:
                listener_dict = {
                    'listener_arn': listener['ListenerArn'],
                    'port': listener['Port'],
                    'protocol': listener['Protocol'],
                    #'ssl_policy': listener['SslPolicy'],
                    'default_actions': listener['DefaultActions']
                }
                try:
                    certificate_arn = listener['Certificates'][0]['CertificateArn']
                except IndexError:
                    pass
                except KeyError:
                    pass
                else:
                    if certificate_arn:
                        listener_dict['certificate_arn'] = certificate_arn
            listener_list.append(listener_dict)
        return listener_list
            

    def _get_elb_info(self, elb):
        elb_info = {
            'load_balancer_arn': elb['LoadBalancerArn'],
            'zones': self._get_zone_info(elb['AvailabilityZones']),
            'name': elb['LoadBalancerName'],
            'dns_name': elb['DNSName'],
            'security_groups': elb['SecurityGroups'],
            'state': elb['State']['Code'],
            'listeners': self._get_listeners(elb['LoadBalancerArn'])
        }

        return elb_info

    def list_elbs(self):
        elb_array = []

        try:
            all_elbs = self.elbv2.describe_load_balancers()
        except BotoServerError as err:
            self.module.fail_json(msg = "%s: %s" % (err.error_code, err.error_message))
        
        if all_elbs:
            if self.names:
                for existing_lb in all_elbs['LoadBalancers']:
                    if existing_lb['LoadBalancerName'] in self.names:
                        elb_array.append(existing_lb)
            else:
                elb_array = all_elbs
        
        return list(map(self._get_elb_info, elb_array))


def main():
    argument_spec = ec2_argument_spec()
    argument_spec.update(
        dict(
            names={'default': [], 'type': 'list'}
        )
    )

    module = AnsibleModule(argument_spec=argument_spec,
                          supports_check_mode=True)
    
    if not HAS_BOTO:
        module.fail_json(msg='boto required for this module')

    region, ec2_url, aws_connect_params = get_aws_connection_info(module)

    if not region:
        module.fail_json(msg="region must be specified")

    names = module.params['names']
    elb_information = ElbInformation(module,
                          names,
                          region,
                          **aws_connect_params)
    ec2_facts_result = dict(changed=False,
                          elbs=elb_information.list_elbs())
    module.exit_json(**ec2_facts_result)

from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

if __name__ == '__main__':
        main()
