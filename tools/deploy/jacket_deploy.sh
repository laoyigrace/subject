#!/bin/bash

if [ -e /root/adminrc ]; then
    source /root/adminrc
elif [ -e /root/keystonerc_admin ]; then
    source /root/keystonerc_admin
fi

HOST_IP=`ip addr |grep inet|grep -v 127.0.0.1|grep -v inet6|grep -E "ens|eth"|awk '{print $2}'|tr -d "addr:" | awk -F '/' '{print $1}'`

ATTRS="mysqldbadm mysqldbpassword mysqldbport dbbackendhost \
subjectdbname subjectdbuser subjectdbpass bind_host \
bind_port backlog registry_host registry_port \
log_dir connection stores default_store filesystem_store_datadir \
auth_uri identity_uri admin_password admin_tenant_name admin_user \
amqp_durable_queues rabbit_host rabbit_port rabbit_hosts \
rabbit_use_ssl rabbit_password rabbit_virtual_host rabbit_ha_queues \
heartbeat_rate flavor state_path endpointsregion publicurl adminurl internalurl \
subject_service"

CONF_FILE=

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
#[ $#  -lt 2 ] && usage

#解析参数
param_parse()
{
	# 可输入的选项参数设置
	ARGS=`getopt -a -o f: -l conf: -- "$@"`
	[ $? -ne 0 ] && usage

	eval set -- "${ARGS}"
	while true
	do
		case "$1" in
		-f|--conf)
			CONF_FILE="$2";
			shift
			;;
		--)
			shift
			break
			;;
			esac
	shift
	done
}

attrs_init()
{
    for attr in ${ATTRS}; do
        crudini --get "${CONF_FILE}" CONF $attr 2>/dev/null
        if [ $? -ne 0 ]; then
            die 1 "get attr($attr) from $CONF_FILE failed!"
        fi
        attr_value=`crudini --get "${CONF_FILE}" CONF $attr`
        eval "export $attr=$attr_value"

        echo "$attr=$attr_value"
    done
}

system_service()
{
    #生成jacket-worker jacket-api.service
    cat << EOF >/usr/lib/systemd/system/ojj-subject-api.service
    [Unit]
    Deacription=Subject API Server
    After=syslog.target network.target

    [Service]
    Type=notify
    NotifyAccess=all
    TimeoutStartSec=0
    Restart=always
    User=subject
    ExecStart=/usr/bin/subject-api --config-file /etc/subject/subject-api.conf

    [Install]
    WantedBy=multi-user.target
EOF

    cat << EOF >/usr/lib/systemd/system/ojj-subject-registry.service
    [Unit]
    Deacription=subject registry Server
    After=syslog.target network.target

    [Service]
    Type=notify
    NotifyAccess=all
    TimeoutStartSec=0
    Restart=always
    User=subject
    ExecStart=/usr/bin/subject-registry --config-file /etc/subject/subject-registry.conf

    [Install]
    WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ojj-subject-api.service
    systemctl enable ojj-subject-registry.service

}

db_init()
{
    #  数据库部署
    mysqlcommand="mysql --port=$mysqldbport --password=$mysqldbpassword --user=$mysqldbadm --host=$dbbackendhost"

    echo "CREATE DATABASE IF NOT EXISTS $subjectdbname default character set utf8;"|$mysqlcommand
    echo "GRANT ALL ON $subjectdbname.* TO '$subjectdbuser'@'%' IDENTIFIED BY '$subjectdbpass';"|$mysqlcommand
    echo "GRANT ALL ON $subjectdbname.* TO '$subjectdbuser'@'localhost' IDENTIFIED BY '$subjectdbpass';"|$mysqlcommand
    echo "GRANT ALL ON $subjectdbname.* TO '$subjectdbuser'@'$subjecthost' IDENTIFIED BY '$subjectdbpass';"|$mysqlcommand

    subject-manage db sync
}

conf_init()
{
    #配置文件的设置
    crudini --set /etc/subject/subject-api.conf DEFAULT bind_host "${bind_host}"
    crudini --set /etc/subject/subject-api.conf DEFAULT bind_port "${bind_port}"
    crudini --set /etc/subject/subject-api.conf DEFAULT backlog "${backlog}"
    crudini --set /etc/subject/subject-api.conf DEFAULT registry_host "${registry_host}"
    crudini --set /etc/subject/subject-api.conf DEFAULT registry_port "${registry_port}"
    crudini --set /etc/subject/subject-api.conf DEFAULT log_dir "${log_dir}"

	#subject_store
    crudini --set /etc/subject/subject-api.conf subject_store stores "${stores}"
    crudini --set /etc/subject/subject-api.conf subject_store default_store "${default_store}"
    crudini --set /etc/subject/subject-api.conf subject_store filesystem_store_datadir "${filesystem_store_datadir}"

    #database
    crudini --set /etc/subject/subject.conf database connection "mysql+pymysql://${subjectdbuser}:${subjectdbpass}@${dbbackendhost}:${mysqldbport}/${subjectdbname}"
    crudini --set /etc/subject/subject.conf database retry_interval 10
    crudini --set /etc/subject/subject.conf database idle_timeout 3600
    crudini --set /etc/subject/subject.conf database min_pool_size 1
    crudini --set /etc/subject/subject.conf database max_pool_size 10
    crudini --set /etc/subject/subject.conf database max_retries 100
    crudini --set /etc/subject/subject.conf database pool_timeout 10

    # keystone
    crudini --set /etc/subject/subject.conf keystone_authtoken auth_uri "${auth_uri}"
    crudini --set /etc/subject/subject.conf keystone_authtoken identity_uri "${identity_uri}"
    crudini --set /etc/subject/subject.conf keystone_authtoken admin_password "${admin_password}"
    crudini --set /etc/subject/subject.conf keystone_authtoken admin_tenant_name "${admin_tenant_name}"
    crudini --set /etc/subject/subject.conf keystone_authtoken admin_user "${admin_user}"


    # rabbit
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit rabbit_host $rabbit_host
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit rabbit_port $rabbit_port
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit rabbit_hosts $rabbit_hosts
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit rabbit_use_ssl ${rabbit_use_ssl}
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit rabbit_password ${rabbit_password}
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit rabbit_virtual_host $rabbit_virtual_host
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit rabbit_ha_queues ${rabbit_ha_queues}
    crudini --set /etc/subject/subject.conf oslo_messaging_rabbit heartbeat_rate ${heartbeat_rate}

    #compute
    crudini --set /etc/subject/subject.conf paste_deploy flavor ${flavor}

}

subject_user_init()
{
    #生成subject用户
    getent group subject >/dev/null || groupadd -r subject --gid 1066
    if ! getent passwd subject >/dev/null; then
      # Id reservation request: https://bugzilla.redhat.com/923891
      useradd -u 1066 -r -g subject -G subject,nobody -d /var/lib/subject/ -s /sbin/nologin -c "OpenStack subject Daemons" subject
    fi

    #加入到sudo中
    cat <<EOF >/etc/sudoers.d/subject
Defaults:subject !requiretty
subject ALL = (root) NOPASSWD: /usr/bin/subject-rootwrap /etc/subject/rootwrap.conf *
EOF

}

main()
{
    script_dir=`dirname $0`
    param_parse $*
    if [ "x$CONF_FILE" = "x" ]; then
        script_dir=`dirname $0`
        CONF_FILE="${script_dir}/subject_conf.ini"
    fi

    if [ ! -e "$CONF_FILE" ]; then
        usage
    fi

    attrs_init
    mkdir -p "${state_path}"
    mkdir -p "${state_path}/subjects"
    mkdir -p "${log_dir}"
    mkdir -p /etc/subject
    conf_init
    db_init
    subject_user_init
    chown subject:subject "${state_path}" -R
    chown subject:subject "${log_dir}"
    system_service

    #keystone中设置subject

    keystone user-get $admin_user || keystone user-create --name $admin_user \
    --tenant $admin_tenant_name --pass $admin_password --email "subject@email"

    keystone user-role-add --user $admin_user --role admin --tenant $admin_tenant_name
    keystone service-get $subject_service || keystone service-create --name $subject_service --description "OpenStack subject service" --type subject

    keystone endpoint-get --service $subject_service || keystone endpoint-create --region $endpointsregion --service $subject_service \
    --publicurl "${publicurl}" \
    --adminurl "${adminurl}" \
    --internalurl "${internalurl}"

    # 创建image对应关系
    #jacket --insecure --debug image-mapper-create 66ecc1c0-8367-477b-92c5-1bb09b0bfa89 fc84fa2c-dafd-498a-8246-0692702532c3

    service ojj-subject-api restart
    service ojj-subject-registry restart
}

main $*
exit 0
