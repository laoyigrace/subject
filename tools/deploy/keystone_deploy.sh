#!/bin/bash

source ./common_var

HOST_IP=`ip addr |grep inet|grep -v 127.0.0.1|grep -v inet6|grep -E "ens|eth"|awk '{print $2}'|tr -d "addr:" | awk -F '/' '{print $1}'`

# 打印帮助信息
usage()
{
cat << HELP
	-f,--conf				subject deploy config file
HELP
	exit 1;
}

#打印错误代码并退出
die()
{
	ecode=$1;
	shift;
	echo -e "${CRED}$*, exit $ecode${C0}" | tee -a $LOG_NAME;
	exit $ecode;
}

mysqlcommand="mysql --port=$mysqldbport --password=$mysqldbpassword --user=$mysqldbadm --host=$dbbackendhost"
db_keystone="keystone"
keystone_user="keystone"
keystone_pass="laoyi@19901013"
admin_pass="laoyi@19901013"
echo "CREATE DATABASE IF NOT EXISTS ${db_keystone} default character set utf8;"|$mysqlcommand
echo "GRANT ALL ON $db_keystone.* TO '$keystone_user'@'%' IDENTIFIED BY '$keystone_pass';"|$mysqlcommand
echo "GRANT ALL ON $db_keystone.* TO '$keystone_user'@'localhost' IDENTIFIED BY '$keystone_pass';"|$mysqlcommand
echo "GRANT ALL ON $db_keystone.* TO '$keystone_user'@'$subjecthost' IDENTIFIED BY '$keystone_pass';"|$mysqlcommand

yum install -y openstack-keystone httpd mod_wsgi


crudini --set /etc/keystone/keystone.conf database connection \
"mysql+pymysql://${keystone_user}:${keystone_pass}@${dbbackendhost}/${db_keystone}"

su -s /bin/sh -c "keystone-manage db_sync" keystone

keystone-manage bootstrap --bootstrap-password ${admin_pass} \
--bootstrap-admin-url http://${HOST_IP}:35357/v3/ \
--bootstrap-internal-url http://${HOST_IP}:35357/v3/ \
--bootstrap-public-url http://${HOST_IP}:5000/v3/ \
--bootstrap-region-id RegionOne

ln -s /usr/share/keystone/wsgi-keystone.conf /etc/httpd/conf.d/

systemctl enable httpd.service
systemctl restart httpd.service
cat << EOF >/root/keystone_adminrc
export OS_USERNAME=admin
export OS_PASSWORD=${admin_pass}
$ export OS_PROJECT_NAME=admin
$ export OS_USER_DOMAIN_NAME=Default
$ export OS_PROJECT_DOMAIN_NAME=Default
$ export OS_AUTH_URL=http://${HOST_IP}:35357/v3
$ export OS_IDENTITY_API_VERSION=3
EOF