#! /bin/bash

USER=$(id -u)
GROUP=$(id -g)

RL_DIR="/opt/rl"
ENV_PATH=".env"

load_licence_info()
{
    # load licence information
    [ ! -f "${ENV_PATH}" ] && {
        echo "FATAL: cannot find the file to load with environment variables for licensing rl-secure" >&2
        exit 101
    }
    source ${ENV_PATH}
}

make_rl_path()
{
    sudo mkdir -p "${RL_DIR}"
    sudo chown "${USER}:${GROUP}" "${RL_DIR}"
}

install_rl_deploy()
{
    pip install rl-deploy
    rl-deploy --version
}

install_rl_secure()
{
    rl-deploy install \
        --no-tracking \
        --location "${RL_DIR}" \
        --encoded-key "${RLSECURE_ENCODED_LICENSE}"\
        --site-key "${RLSECURE_SITE_KEY}"
    ${RL_DIR}/rl-secure --version
}

main()
{
    load_licence_info
    make_rl_path

    install_rl_deploy
    install_rl_secure

    echo "When using rl-secure, use the command as: ${RL_DIR}/rl-secure or add ${RL_DIR} to the front of your path env variable"
}

main "$@"
